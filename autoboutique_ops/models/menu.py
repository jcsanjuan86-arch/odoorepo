"""No menu override is required.

Odoo 19 caches the application launcher itself.  The previous attempt to
make it company-aware intercepted that cache and caused the Autoboutique root
menu to disappear even while Autoboutique was the active company.  Record
rules still protect the vehicle data; app visibility will be handled through
user/company permissions in a later, separately tested change.
"""
