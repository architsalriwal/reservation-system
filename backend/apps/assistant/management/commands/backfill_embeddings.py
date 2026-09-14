from django.core.management.base import BaseCommand

from apps.assistant.embeddings import embed_product_text, product_embedding_source
from apps.catalog.models import Product


class Command(BaseCommand):
    help = "Computes and stores Gemini embeddings for products missing one (RAG product search)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all", action="store_true", help="Re-embed every product, not just ones missing an embedding."
        )

    def handle(self, *args, **options):
        queryset = Product.objects.all() if options["all"] else Product.objects.filter(embedding__isnull=True)
        count = 0
        for product in queryset:
            text = product_embedding_source(product)
            product.embedding = embed_product_text(text)
            product.save(update_fields=["embedding"])
            count += 1
            self.stdout.write(f"Embedded: {product.name}")

        self.stdout.write(self.style.SUCCESS(f"Embedded {count} product(s)."))
