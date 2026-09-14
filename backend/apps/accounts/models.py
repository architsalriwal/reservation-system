from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Django user bridged from a verified Firebase identity."""

    firebase_uid = models.CharField(max_length=128, unique=True, null=True, blank=True)

    def __str__(self):
        return self.email or self.username
