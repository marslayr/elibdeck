# Generated by Django 5.1.4 on 2025-01-03 14:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='room',
            field=models.CharField(default='No hostel.', max_length=10),
        ),
    ]