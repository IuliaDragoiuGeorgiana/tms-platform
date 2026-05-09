"""
Script pentru crearea primului SUPER_ADMIN.
Se rulează o singură dată la setup-ul inițial al platformei.
"""
import sys
from getpass import getpass
from app.database import SessionLocal
from app.models.user import User, RoleEnum
from app.core.security import hash_password


def create_superadmin():
    db = SessionLocal()
    try:
        # Verifică dacă există deja un SUPER_ADMIN
        existing = db.query(User).filter(User.role == RoleEnum.SUPER_ADMIN).first()
        if existing:
            print(f"Există deja un SUPER_ADMIN: {existing.email}")
            response = input("Vrei să creezi încă unul? (y/n): ").strip().lower()
            if response != "y":
                print("Anulat.")
                return

        print("\n=== Creare SUPER_ADMIN ===\n")
        email = input("Email: ").strip()
        full_name = input("Nume complet: ").strip()
        password = getpass("Parolă (min 8 caractere): ")

        if len(password) < 8:
            print("EROARE: Parola trebuie să aibă minim 8 caractere")
            sys.exit(1)

        password_confirm = getpass("Confirmă parola: ")
        if password != password_confirm:
            print("EROARE: Parolele nu se potrivesc")
            sys.exit(1)

        # Verifică email duplicat
        if db.query(User).filter(User.email == email).first():
            print(f"EROARE: Email-ul {email} e deja folosit")
            sys.exit(1)

        # Creează SUPER_ADMIN
        superadmin = User(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role=RoleEnum.SUPER_ADMIN,
            company_id=None,              # SUPER_ADMIN NU aparține vreunei companii
            is_active=True,
            is_approved=True,
            must_change_password=False,   # și-a setat singur parola
        )

        db.add(superadmin)
        db.commit()
        db.refresh(superadmin)

        print(f"\n✓ SUPER_ADMIN creat cu succes!")
        print(f"  ID: {superadmin.id}")
        print(f"  Email: {superadmin.email}")
        print(f"\nTe poți loga acum la http://127.0.0.1:8000/docs → POST /auth/login\n")

    finally:
        db.close()


if __name__ == "__main__":
    create_superadmin()