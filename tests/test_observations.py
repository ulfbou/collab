import json,subprocess,tempfile,unittest
from pathlib import Path
from collab.observations import HostedQuery,HostedRepositoryCollector,ObservationError,observe_local_repository,observe_manifest
class Tests(unittest.TestCase):
 def repo(self):
  d=tempfile.TemporaryDirectory(); r=Path(d.name); subprocess.run(['git','init','-q'],cwd=r,check=True); subprocess.run(['git','config','user.name','T'],cwd=r,check=True); subprocess.run(['git','config','user.email','t@invalid'],cwd=r,check=True); subprocess.run(['git','remote','add','origin','https://github.com/example/repo.git'],cwd=r,check=True); (r/'x').write_text('x\n'); subprocess.run(['git','add','x'],cwd=r,check=True); subprocess.run(['git','commit','-qm','init'],cwd=r,check=True); return d,r
 def test_local(self):
  d,r=self.repo(); self.addCleanup(d.cleanup); (r/'x').write_text('s\n'); subprocess.run(['git','add','x'],cwd=r,check=True); (r/'x').write_text('u\n'); (r/'n').write_text('n')
  o=observe_local_repository(r); self.assertEqual(['x'],o['status']['staged']); self.assertEqual(['x'],o['status']['unstaged']); self.assertEqual(['n'],o['status']['untracked']); self.assertTrue(o['complete'])
 def test_manifest(self):
  d,r=self.repo(); self.addCleanup(d.cleanup); self.assertEqual('not_declared',observe_manifest(r)['status']); p=r/'.collab/repository-manifest.json'; p.parent.mkdir(); p.write_text('{bad'); self.assertEqual('invalid',observe_manifest(r)['structuralValidation']); p.write_text('{"$schema":"id"}'); self.assertEqual('id',observe_manifest(r)['declaredSchemaIdentity'])
 def test_hosted(self):
  calls=[]
  def execute(argv,cwd):
   calls.append(argv); e=argv[-1]
   if e=='repos/example/repo': return b'{"default_branch":"master"}'
   if e.endswith('/issues/62'): return b'{"number":62}'
   return b'[[{"id":1}],[{"id":2}]]'
  o=HostedRepositoryCollector('example/repo',execute=execute).collect(HostedQuery('issue','62')); self.assertEqual(2,o['domains']['issues']['pageCount']); self.assertEqual(2,o['domains']['issues']['itemCount']); self.assertTrue(any('--slurp' in x for x in calls))
 def test_pr_query_collects_handoff_context(self):
  calls=[]
  def execute(argv,cwd):
   calls.append(argv); endpoint=argv[-1]
   if endpoint=='repos/example/repo': return b'{"default_branch":"master"}'
   if endpoint.endswith('/pulls/25'): return b'{"number":25,"head":{"sha":"abc"}}'
   return b'[[{"id":1}]]'
  o=HostedRepositoryCollector('example/repo',execute=execute).collect(HostedQuery('pr','25'))
  related=o['boundedQuery']['related']
  self.assertEqual({'comments','reviews','reviewComments','commits','files'},set(related))
  self.assertTrue(all(value['complete'] for value in related.values()))
  endpoints={call[-1] for call in calls}
  self.assertIn('repos/example/repo/issues/25/comments?per_page=100',endpoints)
  self.assertIn('repos/example/repo/pulls/25/reviews?per_page=100',endpoints)
  self.assertIn('repos/example/repo/pulls/25/comments?per_page=100',endpoints)
  self.assertIn('repos/example/repo/pulls/25/commits?per_page=100',endpoints)
  self.assertIn('repos/example/repo/pulls/25/files?per_page=100',endpoints)

if __name__=='__main__': unittest.main()
