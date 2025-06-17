from setuptools import setup, find_packages
import sys, os

version = '0.1'

setup(
    name='ckanext-portalopendatadk',
    version=version,
    description="Theme for Open Data Denmark Portal",
    long_description='''
    ''',
    classifiers=[], # Get strings from http://pypi.python.org/pypi?%3Aaction=list_classifiers
    keywords='',
    author='Henrik Aagaard',
    author_email='haj@cphsolutionslab.dk',
    url='http://portal.opendata.dk',
    license='',
    packages=find_packages(exclude=['ez_setup', 'examples', 'tests']),
    namespace_packages=['ckanext', 'ckanext.portalopendatadk'],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        # -*- Extra requirements: -*-
    ],
    entry_points='''
        [ckan.plugins]
        # Add plugins here, e.g.
        portalopendatadk=ckanext.portalopendatadk.plugin:PortalOpenDataDKPlugin
        [ckan.rdf.profiles]
        danish_dcat_ap=ckanext.portalopendatadk.dcat_profile:DanishDCATAPProfile
        [babel.extractors]
        ckan = ckan.lib.extract:extract_ckan
    ''',
    message_extractors={
        'ckanext': [
            ('**.py', 'python', None),
            ('**.js', 'javascript', None),
            ('**/templates/**.html', 'ckan', None),
        ],
    }
)
