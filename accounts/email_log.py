from django.db import models


class EmailLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    to_email = models.EmailField()
    subject = models.CharField(max_length=255)

    provider = models.CharField(max_length=50, default="sendgrid")

    success = models.BooleanField(default=False)
    status_code = models.IntegerField(null=True, blank=True)

    response_body = models.TextField(blank=True)
    error = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"{self.created_at} {self.to_email} {self.subject} ({'OK' if self.success else 'FAIL'})"
