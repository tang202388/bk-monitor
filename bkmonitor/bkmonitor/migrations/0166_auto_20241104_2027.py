# Generated by Django 3.2.15 on 2024-11-04 12:27

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('bkmonitor', '0165_merge_20240813_1630'),
    ]

    operations = [
        migrations.AlterField(
            model_name='metriclistcache',
            name='data_label',
            field=models.CharField(db_index=True, default='', max_length=256, verbose_name='db标识'),
        ),
    ]
