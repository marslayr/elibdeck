# Generated by Django 5.1.4 on 2024-12-28 10:10

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('books_catalog', '0007_book_cover_image'),
    ]

    operations = [
        migrations.RenameField(
            model_name='feedback',
            old_name='comments',
            new_name='body',
        ),
    ]