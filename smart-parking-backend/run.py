"""
START THE SERVER:    python run.py

Then open http://localhost:5000/api/parking/locations in your browser to check it works.
(Press Ctrl+C in the terminal to stop.)
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    print("\n  Smart Parking API running at  http://localhost:5000")
    print("  Demo admin : admin@parkease.com  /  Admin@123")
    print("  Demo driver: aarav@example.com   /  User@1234\n")
    # debug=True auto-restarts on code changes. Turn it OFF in real deployments.
    app.run(host="0.0.0.0", port=5000, debug=True)
