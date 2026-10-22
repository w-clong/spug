from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('host', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='group',
            name='is_dynamic',
            field=models.BooleanField(default=False),
        ),
    ]
