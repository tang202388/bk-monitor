# Generated by Django 3.2.15 on 2024-08-26 13:56

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('log_clustering', '0029_auto_20240819_2049'),
    ]

    operations = [
        migrations.RenameField(
            model_name='clusteringconfig',
            old_name='log_count_agg_rt',
            new_name='new_cls_strategy_output',
        ),
        migrations.AddField(
            model_name='clusteringconfig',
            name='new_cls_strategy_enable',
            field=models.BooleanField(default=False, verbose_name='是否开启新类告警'),
        ),
        migrations.AddField(
            model_name='clusteringconfig',
            name='normal_strategy_enable',
            field=models.BooleanField(default=False, verbose_name='是否开启数量突增告警'),
        ),
        migrations.AddField(
            model_name='clusteringconfig',
            name='normal_strategy_output',
            field=models.CharField(blank=True, default='', max_length=255, null=True, verbose_name='日志数量聚合告警输出结果表'),
        ),
    ]