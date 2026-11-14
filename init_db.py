"""Run once to create MySQL tables (not on every web request)."""
from main import Base, engine

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("Nutrition tables are ready.")
