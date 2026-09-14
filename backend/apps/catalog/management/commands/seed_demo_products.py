from django.core.management.base import BaseCommand

from apps.catalog.demo_icons import product_icon_data_uri
from apps.catalog.models import Category, Product

PRODUCTS = [
    dict(
        slug="aria-wireless-headphones",
        name="Aria Wireless Headphones",
        category="Audio",
        description="Active noise cancellation, 40-hour battery, plush memory-foam ear cups.",
        price=4999,
        stock=18,
        icon="headphones",
    ),
    dict(
        slug="nimbus-running-sneakers",
        name="Nimbus Running Sneakers",
        category="Footwear",
        description="Featherlight knit upper with responsive foam cushioning for daily runs.",
        price=3499,
        stock=3,
        icon="sneaker",
    ),
    dict(
        slug="pulse-smartwatch",
        name="Pulse Smartwatch",
        category="Wearables",
        description="Heart-rate, SpO2 and sleep tracking with a 10-day battery life.",
        price=6999,
        stock=9,
        icon="smartwatch",
    ),
    dict(
        slug="drift-mechanical-keyboard",
        name="Drift Mechanical Keyboard",
        category="Accessories",
        description="Hot-swappable switches, PBT keycaps, and per-key RGB.",
        price=5499,
        stock=12,
        icon="keyboard",
    ),
    dict(
        slug="voyage-travel-backpack",
        name="Voyage Travel Backpack",
        category="Bags",
        description="Water-resistant 30L pack with a padded 16-inch laptop sleeve.",
        price=2799,
        stock=25,
        icon="backpack",
    ),
    dict(
        slug="ember-ceramic-mug-set",
        name="Ember Ceramic Mug Set",
        category="Home",
        description="Set of 2 hand-glazed stoneware mugs, dishwasher and microwave safe.",
        price=899,
        stock=40,
        icon="mug",
    ),
    dict(
        slug="halo-desk-lamp",
        name="Halo Desk Lamp",
        category="Home",
        description="Stepless dimming, adjustable color temperature, USB-C fast-charge port.",
        price=1999,
        stock=2,
        icon="lamp",
    ),
    dict(
        slug="summit-insulated-bottle",
        name="Summit Insulated Bottle",
        category="Outdoors",
        description="Double-wall stainless steel, keeps drinks cold 24h or hot 12h.",
        price=1299,
        stock=30,
        icon="bottle",
    ),
]


class Command(BaseCommand):
    help = "Seeds a curated set of demo products with icon art and INR pricing."

    def handle(self, *args, **options):
        for entry in PRODUCTS:
            category_name = entry.pop("category")
            category, _ = Category.objects.get_or_create(
                name=category_name, defaults={"slug": category_name.lower()}
            )
            slug = entry.pop("slug")
            icon = entry.pop("icon")
            product, created = Product.objects.update_or_create(
                slug=slug,
                defaults={
                    **entry,
                    "category": category,
                    "currency": "INR",
                    "reserved": 0,
                    "is_active": True,
                    "image_url": product_icon_data_uri(icon),
                },
            )
            self.stdout.write(f"{'Created' if created else 'Updated'}: {product.name}")

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(PRODUCTS)} demo products."))
