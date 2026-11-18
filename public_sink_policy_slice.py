"""Pure actual controller/host public sink policy, stripped of internal comments."""
from echo_sync import privacy_gate
from echo_sync.gate_text import public_address_allowed

class ControllerPolicy:
    @staticmethod
    def public_lookup_allowed(question,search=False):
        
        return privacy_gate.allowed(question,search) and (not search or public_address_allowed(question))

def lookup_publicly_permitted(controller, question):
    """Public network authority is tied to a live, valid input turn.

    Pre-final prefetch reads the current open input; after admission the
    question's own ledger turn is checked as well. A safe extracted suffix
    cannot authorize disclosure of a different original speaker's speech.
    Fail closed if this relationship cannot be established.
    """
    try:
        if not controller.public_lookup_allowed(question, True):
            return False
        heard=controller.ledger.latest_user()
        if not isinstance(heard,dict) or not heard.get('valid'):
            return False
        raw=heard.get('text') or ''
        if not raw or not public_address_allowed(raw):
            return False
        qid=getattr(controller,'question_id',None)
        if qid:
            origin=controller.ledger.snapshot(qid)
            if (not isinstance(origin,dict) or not origin.get('valid')
                    or not public_address_allowed(origin.get('text',''))):
                return False
        return not controller.question_text or public_address_allowed(controller.question_text)
    except Exception:
        return False

