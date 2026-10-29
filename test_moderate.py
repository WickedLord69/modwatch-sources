import copy
import unittest
from moderate import parse_submission, source_url, approved_catalog, approval_command, handle

def body(filename='Example.dll', url='https://www.lcpdfr.com/downloads/gta5mods/scripts/123-example/', name='Example'):
    return f'''### Filename

{filename}

### Mod name

{name}

### Author

Public Author

### Source URL

{url}

### Search aliases

Example Mod;ExampleMod

### Version comparison

Normal version checks

### Confirmation

- [X] I checked the page supplies this file.
'''

class FakeAPI:
    owner = 'WickedLord69'
    def __init__(self, text=None):
        self.issue = {'number':1, 'state':'open', 'title':'[Source] Example.dll', 'body':text or body()}
        self.comments, self.states, self.published, self.receipts = [], [], [], []
    def request(self, method, path, value=None):
        if method == 'GET' and path == '/issues/1':
            return copy.deepcopy(self.issue)
        raise AssertionError('Unexpected endpoint: ' + path)
    def comment(self, number, text): self.comments.append(text)
    def status(self, number, state, close=False): self.states.append((state,close))
    def receipt(self, number, entry, digest, external): self.receipts.append((entry,digest,external))
    def publish(self, number, entry, replace): self.published.append((entry,replace));return 'Published.'

class ModerationTests(unittest.TestCase):
    def test_form(self):
        entry, digest, external = parse_submission(body())
        self.assertEqual(entry['FileName'],'Example.dll');self.assertEqual(len(digest),64);self.assertFalse(external)
    def test_owner_only(self):
        digest = parse_submission(body())[1]
        self.assertIsNone(approval_command('/approve '+digest,'stranger','WickedLord69',digest))
        self.assertEqual(approval_command('/approve '+digest,'WickedLord69','WickedLord69',digest),'approve')
    def test_edited_submission(self):
        old = parse_submission(body())[1];new = parse_submission(body(name='Changed'))[1]
        with self.assertRaises(ValueError): approval_command('/approve '+old,'WickedLord69','WickedLord69',new)
    def test_external(self):
        entry,digest,external = parse_submission(body(url='https://www.author-site.example/release'))
        self.assertTrue(external);self.assertEqual(entry['Url'],'https://www.author-site.example/release')
        with self.assertRaises(ValueError):approval_command('/approve '+digest,'WickedLord69','WickedLord69',digest,True)
        self.assertEqual(approval_command('/approve-external '+digest,'WickedLord69','WickedLord69',digest,True),'approve-external')
    def test_vehicle_pages(self):
        for url in ('https://www.lcpdfr.com/downloads/gta5mods/vehiclemodels/123-els-car/','https://www.gta5-mods.com/vehicles/els-tahoe','https://www.gta5-mods.com/player/eup-clothes'):
            with self.subTest(url=url),self.assertRaises(ValueError):source_url(url)
    def test_credentials_and_binary(self):
        for url in ('http://example.com/mod','https://a:secret@example.com/mod','https://127.0.0.1/mod','https://localhost.local/mod','https://example.com/a.zip','https://example.com/page?token=secret','file:///C:/secret'):
            with self.subTest(url=url),self.assertRaises(ValueError):source_url(url)
    def test_path_filename(self):
        for name in ('../Example.dll','C:\\private\\Example.dll','scripts/Example.dll','Example.dll\n### Mod name\nInjected'):
            with self.subTest(name=name),self.assertRaises(ValueError):parse_submission(body(filename=name))
    def test_duplicate_fields(self):
        with self.assertRaises(ValueError):parse_submission(body()+'\n### Filename\n\nOther.dll\n')
    def test_markup(self):
        for name in ('```/approve fake','<script>bad</script>','C:\\private'):
            with self.subTest(name=name),self.assertRaises(ValueError):parse_submission(body(name=name))
    def test_normalize_repository(self):
        self.assertEqual(source_url('https://github.com/owner/repo/releases/latest'),('https://github.com/owner/repo',False))
    def test_normalize_nexus(self):
        self.assertEqual(source_url('https://www.nexusmods.com/gta5/mods/42/')[0],'https://www.nexusmods.com/games/gta5/mods/42')
    def test_new_entry(self):
        entry=parse_submission(body())[0];initial={'SchemaVersion':1,'Entries':[]}
        self.assertEqual(approved_catalog(initial,entry)['Entries'],[entry]);self.assertEqual(initial['Entries'],[])
    def test_duplicate_idempotent(self):
        entry=parse_submission(body())[0];initial={'SchemaVersion':1,'Entries':[entry]}
        self.assertEqual(approved_catalog(initial,entry),initial)
    def test_explicit_replacement(self):
        entry=parse_submission(body())[0];other=dict(entry,Url='https://www.gta5-mods.com/scripts/other')
        catalog={'SchemaVersion':1,'Entries':[other]}
        with self.assertRaises(ValueError):approved_catalog(catalog,entry)
        self.assertEqual(approved_catalog(catalog,entry,True)['Entries'],[entry])
    def test_pending_never_publishes(self):
        api=FakeAPI();handle({'issue':api.issue},api)
        self.assertEqual(len(api.receipts),1);self.assertEqual(api.published,[])
    def test_non_owner_never_publishes(self):
        api=FakeAPI();digest=parse_submission(body())[1]
        handle({'issue':api.issue,'comment':{'user':{'login':'stranger'},'body':'/approve '+digest}},api)
        self.assertEqual(api.published,[]);self.assertEqual(api.comments,[])
    def test_owner_approval(self):
        api=FakeAPI();digest=parse_submission(body())[1]
        handle({'issue':api.issue,'comment':{'user':{'login':api.owner},'body':'/approve '+digest}},api)
        self.assertEqual(len(api.published),1);self.assertEqual(api.states,[('published',True)])
    def test_stale_command_does_not_publish(self):
        api=FakeAPI(body(name='Changed'));digest=parse_submission(body())[1]
        handle({'issue':api.issue,'comment':{'user':{'login':api.owner},'body':'/approve '+digest}},api)
        self.assertEqual(api.published,[]);self.assertEqual(len(api.receipts),1)
    def test_reject_and_needs_info(self):
        for action,status,closed in [('reject','rejected',True),('needs-info','needs-information',False)]:
            api=FakeAPI();digest=parse_submission(body())[1]
            handle({'issue':api.issue,'comment':{'user':{'login':api.owner},'body':'/'+action+' '+digest}},api)
            self.assertEqual(api.published,[]);self.assertIn((status,closed),api.states)
    def test_closed_issues_ignored(self):
        api=FakeAPI();api.issue['state']='closed';handle({'issue':api.issue},api);self.assertEqual(api.receipts,[])
    def test_pull_request_comments_ignored(self):
        api=FakeAPI();api.issue['pull_request']={};handle({'issue':api.issue},api);self.assertEqual(api.receipts,[])

if __name__=='__main__':unittest.main()
