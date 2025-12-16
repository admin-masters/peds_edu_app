from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("to_email", models.EmailField(max_length=254)),
                ("subject", models.CharField(max_length=255)),
                ("provider", models.CharField(default="sendgrid", max_length=50)),
                ("success", models.BooleanField(default=False)),
                ("status_code", models.IntegerField(blank=True, null=True)),
                ("response_body", models.TextField(blank=True)),
                ("error", models.TextField(blank=True)),
            ],
        ),
    ]
