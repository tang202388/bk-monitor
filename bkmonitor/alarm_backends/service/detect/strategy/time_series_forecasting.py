# -*- coding: utf-8 -*-
"""
Tencent is pleased to support the open source community by making 蓝鲸智云 - 监控平台 (BlueKing - Monitor) available.
Copyright (C) 2017-2021 THL A29 Limited, a Tencent company. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at http://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""
"""
TimeSeriesForecasting：时序预测算法，基于计算平台的预测结果进行静态阈值检测
"""
import json
import logging
import operator
from typing import List, Tuple, Union

from django.conf import settings
from django.utils.translation import gettext as _

from alarm_backends.service.detect import AnomalyDataPoint, DataPoint
from alarm_backends.service.detect.strategy import (
    BasicAlgorithmsCollection,
    SDKPreDetectMixin,
)
from alarm_backends.templatetags.unit import unit_convert_min, unit_suffix
from bkmonitor.strategy.serializers import TimeSeriesForecastingSerializer
from bkmonitor.utils.time_tools import hms_string
from constants.aiops import SDKDetectStatus
from core.drf_resource import api
from core.unit import load_unit

logger = logging.getLogger("detect")


class TimeSeriesForecasting(BasicAlgorithmsCollection, SDKPreDetectMixin):
    """
    智能异常检测（动态阈值算法）
    """

    GROUP_PREDICT_FUNC = api.aiops_sdk.tf_group_predict
    PREDICT_FUNC = api.aiops_sdk.tf_predict
    WITH_HISTORY_ANOMALY = False

    OPERATOR_MAPPINGS = {
        "gt": operator.gt,
        "gte": operator.ge,
        "lt": operator.lt,
        "lte": operator.le,
        "eq": operator.eq,
        "neq": operator.ne,
    }

    OPERATOR_DESC = {
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "eq": "=",
        "neq": "!=",
    }

    desc_tpl = "{method_desc} {threshold}{unit_suffix}"

    def detect(self, data_point):
        if data_point.item.query_configs[0]["intelligent_detect"].get("use_sdk", False):
            # 历史依赖准备就绪才开始检测
            if data_point.item.query_configs[0]["intelligent_detect"]["status"] == SDKDetectStatus.PREPARING:
                raise Exception("Strategy history dependency data not ready")

            # 优先从预检测结果中获取检测结果
            if hasattr(self, "_local_pre_detect_results"):
                predict_result_point = self.fetch_pre_detect_result_point(data_point)
                if predict_result_point:
                    return super().detect(predict_result_point)
                else:
                    raise Exception("Pre delete error.")
            else:
                return self.detect_by_sdk(data_point)
        else:
            return self.detect_by_bkdata(data_point)

    def detect_by_sdk(self, data_point):
        dimensions = self.generate_dimensions(data_point)
        predict_params = {
            "data": [{"value": data_point.value, "timestamp": data_point.timestamp * 1000}],
            "dimensions": dimensions,
            "predict_args": {
                "granularity": "T",
                "mode": "serving",
                **{arg_key.lstrip("$"): arg_value for arg_key, arg_value in self.validated_config["args"].items()},
            },
        }

        predict_result = self.PREDICT_FUNC(**predict_params)
        dimension_fields = getattr(data_point, "dimension_fields", None) or list(data_point.dimensions.keys())

        return self.detect_by_bkdata(
            DataPoint(
                accessed_data={
                    "record_id": data_point.record_id,
                    "value": data_point.value,
                    "values": predict_result[0],
                    "time": int(predict_result[0]["timestamp"] / 1000),
                    "dimensions": data_point.dimensions,
                    "dimension_fields": dimension_fields,
                },
                item=data_point.item,
            )
        )

    def detect_by_bkdata(self, data_point):
        bound_type = self.validated_config.get("bound_type", TimeSeriesForecastingSerializer.BoundType.MIDDLE)

        if bound_type == TimeSeriesForecastingSerializer.BoundType.UPPER:
            value_field = "upper_bound"
            value_desc = _("预测上界")
        elif bound_type == TimeSeriesForecastingSerializer.BoundType.LOWER:
            value_field = "lower_bound"
            value_desc = _("预测下界")
        else:
            value_field = "predict"
            value_desc = _("预测值")

        predict_values = self.fetch_predict_values(data_point, value_field)
        if not predict_values:
            # 如果拿不到预测值，说明时序预测模型还没接入完，此时不做检测
            return []

        # 做毫秒单位转换
        duration = self.validated_config["duration"]

        current_time = data_point.timestamp
        for ts, value in predict_values:
            if ts > current_time + duration:
                break
            anomaly_point = self._threshold_detect(value, data_point)
            if not anomaly_point:
                continue

            value, suffix = self.anomaly_message_suffix(value, data_point)
            anomaly_point.anomaly_message = f"{data_point.item.name} {anomaly_point.anomaly_message}" + _(
                ", 将于{predict_time}后满足条件, {value_desc}{value}{unit}"
            ).format(predict_time=hms_string(ts - current_time), value=value, unit=suffix, value_desc=value_desc)
            anomaly_point.context["predict_point"] = [value, ts]
            return [anomaly_point]

        return []

    def _threshold_detect(self, value: float, data_point) -> Union[AnomalyDataPoint, None]:
        """
        静态阈值检测
        """
        threshold_config = self.validated_config["thresholds"]
        for and_configs in threshold_config:
            for and_config in and_configs:
                method = and_config["method"]
                threshold = and_config["threshold"]
                op = self.OPERATOR_MAPPINGS[method]
                actual_value = unit_convert_min(value, data_point.unit)
                excepted_value = unit_convert_min(threshold, data_point.unit, self.unit)
                if not op(actual_value, excepted_value):
                    break
            else:
                # 只要有一组满足阈值判断，则认为满足条件
                anomaly_point = AnomalyDataPoint(data_point=data_point, detector=self)
                anomaly_point.anomaly_message = _(" 且 ").join(
                    [
                        self.desc_tpl.format(
                            method_desc=self.OPERATOR_DESC[and_config["method"]],
                            threshold=and_config["threshold"],
                            unit_suffix=unit_suffix(data_point.unit, self.unit),
                        )
                        for and_config in and_configs
                    ]
                )
                return anomaly_point

    def anomaly_message_template_tuple(self, data_point):
        return "", ""

    @classmethod
    def anomaly_message_suffix(cls, value: float, data_point):
        """
        异常描述模板后缀
        """
        unit = load_unit(data_point.unit)
        value, suffix = unit.fn.auto_convert(value, decimal=settings.POINT_PRECISION)
        return value, suffix

    @classmethod
    def fetch_predict_values(cls, data_point: DataPoint, value_field: str) -> List[Tuple[int, float]]:
        """
        提取预测值
        """
        values = getattr(data_point, "values", {})
        if value_field not in values:
            return []

        try:
            predict_mappings = json.loads(values[value_field])
            predict_values = [(int(ts) // 1000, value) for ts, value in predict_mappings.items()]
        except Exception as e:
            logger.info("[TimeSeriesForecasting] get extra context error: %s, origin data: %s", e, values[value_field])
            return []

        predict_values.sort(key=lambda v: v[0])
        return predict_values
