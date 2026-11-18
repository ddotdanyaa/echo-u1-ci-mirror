"""Pure actual controller/host public sink policy, stripped of internal comments."""
from echo_sync import privacy_gate
from echo_sync.gate_text import public_address_allowed

class ControllerPolicy:
    @staticmethod
    def public_lookup_allowed(question,search=False):
        
        return privacy_gate.allowed(question,search) and (not search or public_address_allowed(question))

def lookup_publicly_permitted(controller, question):
    
    try:
        if not controller.public_lookup_allowed(question, True):
            return False
        heard=controller.ledger.latest_user()
        raw=heard.get('text', '') if isinstance(heard, dict) else ''
        return (not raw or public_address_allowed(raw)) and (
            not controller.question_text or public_address_allowed(controller.question_text))
    except Exception:
        return False

