from django.contrib.auth.tokens import PasswordResetTokenGenerator


class DoctorPasswordTokenGenerator(PasswordResetTokenGenerator):
    """Token generator for doctor password setup/reset."""


doctor_password_token = DoctorPasswordTokenGenerator()
