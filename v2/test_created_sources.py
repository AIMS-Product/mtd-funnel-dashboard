"""Created leads share VP offer scope and all-contact source fallback."""
import unittest
from datetime import date, datetime
from unittest.mock import patch
import build
from aggregates import vp_business_line, vp_appointment_bookings

class CreatedSourceTests(unittest.TestCase):
    def test_created_scope_and_booking_offer_policy_agree(self):
        for line in (None, '', 'Vendingpreneurs (VP)', 'The Land Geek (TLG)', 'Ben Kelly (BK)', 'Acquisition Ace (AA)'):
            with self.subTest(line=line):
                selected=vp_appointment_bookings([{'business_line':line,'appointment_closer':'user_vp'}],{'user_vp':'Luke Herman'})
                self.assertEqual(vp_business_line(line),bool(selected))

    def test_unbooked_created_leads_get_all_contacts_and_other_lines_stay_out(self):
        leads=[{'id':key,'date_created':'2026-11-02T16:00:00Z','status_id':'active',
                f'custom.{build.RULES["lead_fields"]["offer"]}':line}
               for key,line in [('vp','Vendingpreneurs (VP)'),('blank',None),('tlg','The Land Geek (TLG)'),('bk','Ben Kelly (BK)')]]
        calls=[]
        class Reader:
            def meetings_created_in_window(self,*args):return []
            def meeting_history_for_leads(self,*args):return []
            def pages(self,endpoint,params=None):return []
        def contacts(reader,lid):
            calls.append(lid)
            # An older contact, not one created inside the report period.
            return [{'id':'old-contact','date_created':'2025-01-01T00:00:00Z',
                     f'custom.{build.RULES["contact_utm_fields"]["source"]}':'youtube'}]
        with patch.object(build,'fetch_created_leads',return_value=leads),patch.object(build,'fetch_won_opportunities',return_value=[]),patch.object(build,'fetch_contacts',side_effect=contacts):
            result=build.build_dataset(Reader(),datetime(2026,11,17,12,tzinfo=build.PACIFIC),date(2026,11,1))
        self.assertCountEqual(calls,['vp','blank'])
        self.assertEqual(result['totals']['leads_created'],2)
        self.assertEqual(result['channels'][0]['channel'],'YouTube')
        self.assertEqual(result['channels'][0]['leads_created'],2)
        self.assertEqual(result['totals']['bookings'],0)

    def test_original_source_precedes_legacy_and_contact_attribution(self):
        contact={f'custom.{build.RULES["contact_utm_fields"]["source"]}':'instagram'}
        self.assertEqual(build.source_resolve({'original_source':'YouTube','funnel':'Reactivation Scrapers'},[contact]),('YouTube','original_source'))
        self.assertEqual(build.source_resolve({'funnel':'Website'},[contact]),('Website','lead_funnel_origin'))
        self.assertEqual(build.source_resolve({'funnel':'Reactivation Scrapers'},[contact])[0],'Instagram')
        self.assertEqual(build.source_resolve({'funnel':'Reactivation Scrapers'},[])[0],'Unknown (Needs Review)')

if __name__=='__main__':unittest.main()
