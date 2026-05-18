"""
Serviciu email pentru TMS.

În etapa curentă, emailurile sunt afișate în terminal pentru testare.
Ulterior, acest serviciu va fi conectat la un provider real de email.
"""


def send_password_reset_email(
    to_email: str,
    to_name: str,
    reset_token: str,
) -> bool:
    """
    Trimite email cu link de resetare parolă.

    Pentru moment, afișează linkul în terminal.
    """
    reset_link = f"http://localhost:4200/reset-password?token={reset_token}"

    print("\n" + "=" * 80)
    print("EMAIL RESETARE PAROLĂ")
    print(f"Către: {to_name} <{to_email}>")
    print("Subiect: Resetare parolă TMS Platform")
    print(f"Link resetare: {reset_link}")
    print("Tokenul expiră în 15 minute.")
    print("=" * 80 + "\n")

    return True


def send_temporary_password_email(
    to_email: str,
    to_name: str,
    temporary_password: str,
) -> bool:
    """
    Trimite email cu parola temporară pentru conturile create/invitate.

    Pentru moment, afișează parola în terminal.
    În versiunea finală, parola nu trebuie afișată în Swagger/frontend.
    """
    print("\n" + "=" * 80)
    print("EMAIL CONT CREAT")
    print(f"Către: {to_name} <{to_email}>")
    print("Subiect: Cont creat în TMS Platform")
    print(f"Parolă temporară: {temporary_password}")
    print("La prima autentificare, utilizatorul trebuie să schimbe parola.")
    print("=" * 80 + "\n")

    return True