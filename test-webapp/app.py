import os
import requests as http
from flask import Flask, render_template

app = Flask(__name__)

# When set, frontend fetches data from the api-service (multi-repo mode).
# Unset = standalone mode using hardcoded data (single-repo demo).
API_SERVICE_URL = os.environ.get("API_SERVICE_URL", "")

PRODUCTS = [
    {
        "id": 1,
        "name": "Laptop Pro 15",
        "price": 1299.99,
        "stock": 45,
        "discount": 10,
        "category": "Computers",
        "description": "High-performance laptop with 15-inch display, 16GB RAM, 512GB SSD.",
        "reviews": [5, 4, 5, 3, 4],
    },
    {
        "id": 2,
        "name": "Wireless Headphones",
        "price": 199.99,
        "stock": 12,
        "discount": 20,
        "category": "Audio",
        "description": "Noise-cancelling over-ear headphones with 30-hour battery life.",
        "reviews": [4, 5, 4],
    },
    {
        "id": 3,
        "name": "USB-C Hub",
        "price": 49.99,
        "stock": 200,
        "discount": 0,
        "category": "Accessories",
        "description": "7-in-1 USB-C hub with HDMI, USB 3.0, SD card reader, and PD charging.",
        "reviews": [],  # no reviews yet — triggers Bug 1 (single-repo mode)
    },
    {
        "id": 4,
        "name": "Mechanical Keyboard",
        "price": 149.99,
        "stock": 8,
        "discount": 15,
        "category": "Peripherals",
        "description": "Compact TKL mechanical keyboard with Cherry MX switches and RGB backlight.",
        "reviews": [5, 5, 4, 5],
    },
]


def calculate_sale_price(price, discount):
    return round(price * (1 - discount / 100), 2)


# ── Single-repo mode (no API_SERVICE_URL) ────────────────────────────────────

@app.route("/")
def index():
    if API_SERVICE_URL:
        return index_multi_repo()

    products = []
    for p in PRODUCTS:
        product = p.copy()
        product["sale_price"] = calculate_sale_price(p["price"], p["discount"])
        products.append(product)
    return render_template("index.html", products=products, mode="single-repo")


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    if API_SERVICE_URL:
        return product_detail_multi_repo(product_id)

    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if not product:
        return render_template("404.html"), 404

    avg_rating = (
        sum(product["reviews"]) / len(product["reviews"])
        if product["reviews"]
        else None
    )

    sale_price = calculate_sale_price(product["price"], product["discount"])
    return render_template(
        "product.html",
        product=product,
        avg_rating=round(avg_rating, 1) if avg_rating is not None else None,
        sale_price=sale_price,
        mode="single-repo",
    )


# ── Multi-repo mode (API_SERVICE_URL is set) ──────────────────────────────────

def index_multi_repo():
    products = http.get(f"{API_SERVICE_URL}/api/products", timeout=5).json()
    for p in products:
        # BUG (multi-repo): api-service renamed `sale_price` → `final_price`
        # Frontend still reads `sale_price` so all discounted prices show as $0.00
        # Fix (option A): update api-service to return `sale_price` again
        # Fix (option B): update this line to read `final_price`
        p["sale_price"] = p.get("sale_price", 0.0)
    return render_template("index.html", products=products, mode="multi-repo")


def product_detail_multi_repo(product_id):
    resp = http.get(f"{API_SERVICE_URL}/api/products/{product_id}", timeout=5)
    if resp.status_code == 404:
        return render_template("404.html"), 404

    product = resp.json()
    product["sale_price"] = product.get("sale_price", 0.0)  # same field name bug
    avg_rating = product.get("avg_rating")
    sale_price = product["sale_price"]
    return render_template(
        "product.html",
        product=product,
        avg_rating=avg_rating,
        sale_price=sale_price,
        mode="multi-repo",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
