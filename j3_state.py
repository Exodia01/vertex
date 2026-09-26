"""J3 state machine §8. Append-only, illegal transitions rejected."""
LEGAL={
 "raw_observation":["interpreted_expectation"],
 # a clarifying question is answered by the customer, which is a customer_response
 "interpreted_expectation":["banking_equivalent","customer_response"],
 "banking_equivalent":["analysis"],
 "analysis":["challenge","customer_response","stabilized_state"],
 "challenge":["customer_response"],
 "customer_response":["banking_equivalent","analysis","stabilized_state"],
 "stabilized_state":["monitoring"],
 "monitoring":["analysis"],
}
DATACLASS={"observed_data","inferred_data","ai_hypothesis","customer_confirmed_data","customer_rejected_interpretation"}
class JournalStore:
    def __init__(self):
        self.entries=[]; self.seq=0
    def transition(self, aspiration_id, frm, to, data_class, payload, evidence_ref, actor):
        if data_class not in DATACLASS: raise ValueError(f"bad data_class {data_class}")
        if frm is not None and to not in LEGAL.get(frm,[]):
            raise ValueError(f"illegal {frm}->{to}")
        self.seq+=1
        e={"entry_id":f"e{self.seq:03d}","aspiration_id":aspiration_id,"state":to,
           "data_class":data_class,"payload":payload,"evidence_ref":evidence_ref,
           "actor":actor,"created_at":f"t{self.seq:03d}"}
        self.entries.append(e)
        return e
    def history(self, aspiration_id):
        return [e for e in self.entries if e["aspiration_id"]==aspiration_id]
