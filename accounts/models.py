from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Project user.

    Declared up front (even though it adds nothing yet) so future profile
    fields can be added without the painful swap-the-user-model migration
    that Django makes hard to do after the fact.
    """

    class Meta(AbstractUser.Meta):
        pass

    def __str__(self):
        return self.get_username()
