#!/usr/bin/env python3
"""XTrader License Manager — entrypoint del tool del PROPRIETARIO (issue #140, PR 3b).

Tool SEPARATO dal bridge: genera le chiavi e firma le licenze. La logica vive in `license_manager`
(mai nell'EXE del bridge — invariante #1). Si lancia da sorgente sul PC del proprietario:

    python license_manager_main.py

L'EXE dedicato (workflow di build) arriva in una PR successiva.
"""

from license_manager.gui import LicenseManagerApp

if __name__ == "__main__":
    LicenseManagerApp().mainloop()
