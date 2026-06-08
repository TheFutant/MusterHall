from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()


class SignupTests(TestCase):
    @override_settings(REGISTRATION_OPEN=True)
    def test_open_signup_creates_user_and_logs_in(self):
        resp = self.client.post(
            reverse("signup"),
            {
                "username": "newhobbyist",
                "email": "new@example.com",
                "password1": "a-strong-pw-9923",
                "password2": "a-strong-pw-9923",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username="newhobbyist").exists())
        # Logged in immediately after signup.
        self.assertIn("_auth_user_id", self.client.session)

    @override_settings(REGISTRATION_OPEN=False)
    def test_closed_signup_returns_404(self):
        resp = self.client.get(reverse("signup"))
        self.assertEqual(resp.status_code, 404)
