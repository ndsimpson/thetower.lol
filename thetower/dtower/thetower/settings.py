"""
Django settings for thetower project.

Generated by 'django-admin startproject' using Django 4.2.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.2/ref/settings/
"""

from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path("/data")


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = "/data/static"


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "tower.sqlite3",
        'OPTIONS': {
            'timeout': 60,  # Timeout in seconds
        }
    }
}


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/


# SECURITY WARNING: keep the secret key used in production secret!
with open("SECRET_KEY", "r") as infile:
    SECRET_KEY = infile.read()


ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "116.203.133.96",
    "thetower.lol",
    "towerfans.lol",
    "65.109.4.244",
    "api.thetower.lol",
    "admin.thetower.lol",
]

CSRF_TRUSTED_ORIGINS = [
    "https://thetower.lol",
    "https://admin.thetower.lol",
    "https://api.thetower.lol",
    "https://hidden.thetower.lol",
    "https://test.thetower.lol",
]


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "whitenoise.runserver_nostatic",
    "rest_framework",
    "django_extensions",
    "dtower.sus",
    "dtower.tourney_results",
    "colorfield",
    "simple_history",
    "axes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "axes.middleware.AxesMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "thetower.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "thetower.wsgi.application"


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Whitenoise settings
WSGI_APPLICATION = "thetower.wsgi.application"
ASGI_APPLICATION = "thetower.asgi.application"


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django.db.backends": {
            "level": "DEBUG",
            "handlers": ["console"],
        },
    },
}


# Django Axes Configuration for Login Tracking
AUTHENTICATION_BACKENDS = [
    # AxesStandaloneBackend should be the first backend in the AUTHENTICATION_BACKENDS list.
    'axes.backends.AxesStandaloneBackend',

    # Django ModelBackend is the default authentication backend.
    'django.contrib.auth.backends.ModelBackend',
]

# Axes settings for django-axes 8.0.0+
AXES_FAILURE_LIMIT = 5  # Number of failed login attempts before lockout
AXES_COOLOFF_TIME = 1  # Time in hours to wait after lockout
AXES_LOCKOUT_CALLABLE = None  # Use default lockout behavior
AXES_LOCK_OUT_AT_FAILURE = True  # Lock out after failure limit
AXES_VERBOSE = True  # Verbose logging
AXES_RESET_ON_SUCCESS = True  # Reset failure count on successful login
AXES_LOCKOUT_TEMPLATE = None  # Use default lockout template
AXES_ENABLE_ADMIN = True  # Enable admin interface for axes

# Modern django-axes configuration
AXES_HANDLER = 'axes.handlers.database.AxesDatabaseHandler'  # Use database handler
AXES_LOCKOUT_PARAMETERS = ['ip_address', 'username']  # Lock by combination of IP and username

# IP Address Detection for Proxies (CloudFlare + nginx configuration)
AXES_PROXY_COUNT = 2  # CloudFlare + nginx = 2 proxies
AXES_META_PRECEDENCE_ORDER = [
    'HTTP_CF_CONNECTING_IP',  # CloudFlare's real IP header (most reliable)
    'HTTP_X_FORWARDED_FOR',   # Standard forwarded header (may contain proxy chain)
    'HTTP_X_REAL_IP',         # nginx real_ip module header
    'REMOTE_ADDR',            # Fallback to direct connection
]
