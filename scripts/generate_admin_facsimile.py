import io
import sys
import os
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PIL import Image
from scripts.generate_all_users_facsimile import generate_facsimile_image

def main():
    admin_name = "Адміністратор"
    print("Generating perfect facsimile signature...")
    facsimile_bytes = generate_facsimile_image(admin_name)
    
    # Make sure we use the correct database URL
    db_path = project_root / "portal" / "portal.db"
    if "PORTAL_DATABASE_URL" not in os.environ:
        if db_path.exists():
            os.environ["PORTAL_DATABASE_URL"] = f"sqlite:///{db_path}"
            print(f"Using database at: {db_path}")
        else:
            print("Warning: PORTAL_DATABASE_URL not set and portal.db not found at default location.")

    from portal.db import init_db, SessionLocal, User, UserRole

    # Initialize database if needed (idempotent)
    init_db()

    with SessionLocal() as session:
        # Look for the admin user
        admin = session.query(User).filter(User.role == UserRole.ADMIN.value).first()
        if not admin:
            admin = session.query(User).filter(User.email == "admin@dilovod.local").first()
            
        if not admin:
            print("No admin user found. Creating default admin account...")
            admin = User(
                email="admin@dilovod.local",
                name="Адміністратор",
                position="Адміністратор",
                role=UserRole.ADMIN.value,
                password_hash=User.hash_password("admin"),
            )
            session.add(admin)
            session.commit()
            session.refresh(admin)

        # Assign facsimile signature
        admin.facsimile_blob = facsimile_bytes
        admin.facsimile_mime = "image/png"
        session.commit()
        session.refresh(admin)

        # Also save a copy as a PNG file in the repository root
        output_file = project_root / "admin_facsimile.png"
        output_file.write_bytes(facsimile_bytes)

        print("--------------------------------------------------")
        print(f"Facsimile signature successfully assigned to user:")
        print(f"  ID:       {admin.id}")
        print(f"  Name:     {admin.name}")
        print(f"  Email:    {admin.email}")
        print(f"  Role:     {admin.role}")
        print(f"  Has Facs: {admin.facsimile_blob is not None}")
        print(f"  Saved to: {output_file}")
        print("--------------------------------------------------")

if __name__ == "__main__":
    main()
