import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parent))
from aggregates import vp_appointment_bookings
from outcome_core import HistoryReader
from publish_shadow import public_data,TOTAL_FIELDS


class SharedPublicationTests(unittest.TestCase):
    def test_mtd_keeps_historical_appointment_credit_without_reassignment(self):
        rows=[{'owner':'old','business_line':'Vendingpreneurs (VP)','appointment_closer':'scott'},
              {'owner':'scott','business_line':'','appointment_closer':'eric'},
              {'owner':'scott','business_line':'Ben Kelly (BK)','appointment_closer':'scott'}]
        selected=vp_appointment_bookings(rows,{'scott':'Scott Seymour','eric':'Eric Piccione'})
        self.assertEqual(len(selected),2)
        self.assertEqual([row['owner'] for row in selected],['scott','eric'])

    def test_private_won_evidence_is_not_in_public_mtd(self):
        raw={'totals':{key:0 for key in TOTAL_FIELDS},'channels':[],'breakdowns':{},'period':'2026-11-01 through 2026-11-19 PT',
             'source_cutoff':'2026-11-19T13:45:00-08:00','generated_at':'2026-11-19T13:45:00-08:00','rules_version':'approved',
             'counted_meetings':0,'excluded_repeat_candidates':0,'won_rows':[{'lead_name':'PRIVATE-CUSTOMER','lead_id':'private-lead'}]}
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'raw.json';source.write_text(json.dumps(raw));public=public_data(source)
        self.assertNotIn('won_rows',public);self.assertNotIn('PRIVATE-CUSTOMER',json.dumps(public))
