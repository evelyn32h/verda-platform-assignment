"""Check the promised adoption boundary and unchanged app behavior before live sync."""
from pathlib import Path
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
class GitOpsPolicyTests(unittest.TestCase):
    def test_workload_and_probes_are_unchanged_and_no_platform_objects_are_adopted(self):
        old=list(yaml.safe_load_all((ROOT/'manifests/app.yaml').read_text(encoding='utf-8')))
        old=[o for o in old if o['kind']!='Namespace']
        new=list(yaml.safe_load_all((ROOT/'gitops/demo/app.yaml').read_text(encoding='utf-8')))
        self.assertEqual(len(new),7)
        for expected,actual in zip(old,new):
            self.assertEqual(actual['metadata']['namespace'],'demo')
            self.assertNotIn(actual['kind'],('Secret','Namespace','Role','RoleBinding'))
            safety=actual['metadata']['annotations'].pop('argocd.argoproj.io/sync-options')
            self.assertEqual(set(safety.split(',')),{'Prune=false','Delete=false'})
            if not actual['metadata']['annotations']: actual['metadata'].pop('annotations')
            if actual['kind']=='ConfigMap' and actual['metadata']['name']=='demo-content':
                self.assertIn('The platform is running.',actual['data']['index.html'])
                actual['data'].pop('index.html'); expected['data'].pop('index.html')
            self.assertEqual(actual,expected)

    def test_manual_sync_and_namespace_preservation(self):
        app=yaml.safe_load((ROOT/'gitops/argocd/application.yaml').read_text())
        self.assertNotIn('automated',app['spec']['syncPolicy'])
        self.assertNotIn('finalizers',app['metadata'])
        options=app['spec']['syncPolicy']['syncOptions']
        self.assertTrue({'Prune=false','Delete=false','FailOnSharedResource=true'}<=set(options))
        self.assertNotIn('CreateNamespace=true',options)

    def test_project_restricts_repository_namespace_and_resource_types(self):
        project=next(yaml.safe_load_all((ROOT/'gitops/argocd/project.yaml').read_text()))['spec']
        self.assertEqual(project['destinations'],[{'server':'https://kubernetes.default.svc','namespace':'demo'}])
        self.assertEqual(project['sourceRepos'],['https://github.com/evelyn32h/verda-platform-assignment.git'])
        self.assertEqual(project['clusterResourceBlacklist'],[{'group':'*','kind':'*'}])
        self.assertEqual({r['kind'] for r in project['namespaceResourceWhitelist']},{'ConfigMap','Service','Deployment','Ingress','TLSStore'})

if __name__=='__main__': unittest.main()
