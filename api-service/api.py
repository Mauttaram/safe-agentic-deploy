from flask import Flask, jsonify

app = Flask(__name__)

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
        "reviews": [],
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


def compute_sale_price(price, discount):
    return round(price * (1 - discount / 100), 2)


@app.route("/api/products")
def list_products():
    result = []
    for p in PRODUCTS:
        product = p.copy()
        product["sale_price"] = compute_sale_price(p["price"], p["discount"])
        result.append(product)
    return jsonify(result)


@app.route("/api/products/<int:product_id>")
def get_product(product_id):
    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    result = product.copy()
    result["sale_price"] = compute_sale_price(product["price"], product["discount"])
    reviews = product["reviews"]
    result["avg_rating"] = round(sum(reviews) / len(reviews), 1) if reviews else None
    return jsonify(result)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "api-service"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001, debug=True)
