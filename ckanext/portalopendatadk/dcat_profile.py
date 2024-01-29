# -*- coding: utf-8 -*-

import json
import logging
import datetime
import json
import os

from ckantoolkit import config

import rdflib
from rdflib import URIRef, BNode, Literal
from rdflib.namespace import Namespace, RDF, XSD, SKOS

from geomet import wkt, InvalidGeoJSONException

from ckan.plugins import toolkit
from ckan.lib.munge import munge_tag

from ckanext.dcat.utils import (
    resource_uri,
    publisher_uri_from_dataset_dict,
    DCAT_EXPOSE_SUBCATALOGS,
    DCAT_CLEAN_TAGS,
)
from ckanext.dcat.profiles import RDFProfile, CleanedURIRef, URIRefOrLiteral

from ckanext.portalopendatadk import helpers as oddk_helpers


log = logging.getLogger(__name__)


DC = Namespace('http://purl.org/dc/elements/1.1/')
DCT = Namespace('http://purl.org/dc/terms/')
DCAT = Namespace('http://www.w3.org/ns/dcat#')
DCAT_AP = Namespace('http://data.europa.eu/r5r/')
ADMS = Namespace('http://www.w3.org/ns/adms#')
VCARD = Namespace('http://www.w3.org/2006/vcard/ns#')
FOAF = Namespace('http://xmlns.com/foaf/0.1/')
SCHEMA = Namespace('http://schema.org/')
TIME = Namespace('http://www.w3.org/2006/time')
LOCN = Namespace('http://www.w3.org/ns/locn#')
GSP = Namespace('http://www.opengis.net/ont/geosparql#')
OWL = Namespace('http://www.w3.org/2002/07/owl#')
SPDX = Namespace('http://spdx.org/rdf/terms#')
PROF = Namespace('http://www.w3.org/ns/dx/prof/')
SKOS = Namespace('http://www.w3.org/2004/02/skos/core#')
DQV = Namespace('http://www.w3.org/ns/dqv#')
PROV = Namespace('http://www.w3.org/ns/prov#')
ODRL = Namespace('http://www.w3.org/ns/odrl/2/')
ORG = Namespace('http://www.w3.org/ns/org#')

namespaces = {
    'dc': DC,
    'dct': DCT,
    'dcat': DCAT,
    'dcat-ap': DCAT_AP,
    'adms': ADMS,
    'vcard': VCARD,
    'foaf': FOAF,
    'schema': SCHEMA,
    'time': TIME,
    'locn': LOCN,
    'gsp': GSP,
    'owl': OWL,
    'spdx': SPDX,
    'prof': PROF,
    'skos': SKOS,
    'dqv': DQV,
    'prov': PROV,
    'odrl': ODRL,
    'org': ORG,
}

GEOJSON_IMT = 'https://www.iana.org/assignments/media-types/application/vnd.geo+json'
EUROPA_BASE_URI = 'http://publications.europa.eu/resource/'
FREQUENCY_BASE_URI = 'http://publications.europa.eu/resource/authority/frequency/'
FORMAT_BASE_URI = 'http://publications.europa.eu/resource/authority/file-type/'
LANGUAGE_BASE_URI = 'http://publications.europa.eu/resource/dataset/language/'
ACCESS_RIGHTS_URI = 'http://publications.europa.eu/resource/authority/access-right/'
DATA_THEME_BASE_URI = 'http://publications.europa.eu/resource/authority/data-theme/'
LICENSES_BASE_URI = 'http://publications.europa.eu/resource/authority/licence/'
PLANNED_AVAILABILITY_URI = (
    'http://data.europa.eu/r5r/availability/'
)
MEDIA_TYPES_BASE_URI = 'http://www.iana.org/assignments/media-types/'
CONFORMS_TO = 'https://digst.github.io/DCAT-AP-DK/releases/v.2.0/docs/'


def _get_from_file(file_name):
    try:
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(cur_dir, 'dcat/{}'.format(file_name))

        with open(file_path, 'r') as file:
            return json.load(file)
    except Exception as e:
        log.error('Error reading %s: %s' % (file_name, e))
        return {}


GROUP_TO_THEME = _get_from_file('group_to_theme.json')
PLANNED_AVAILABILITY_LABELS = _get_from_file('planned_availability_skos.json')
DATA_THEME_LABELS = _get_from_file('data_themes_skos.json')
ACCESS_RIGHTS_LABELS = _get_from_file('access_rights_skos.json')
LICENSES = _get_from_file('licenses.json')


class DanishDCATAPProfile(RDFProfile):
    """
    An RDF profile for the Danish DCAT-AP profile.
    """

    def parse_dataset(self, dataset_dict, dataset_ref):
        dataset_dict['extras'] = []
        dataset_dict['resources'] = []

        # Basic fields
        for key, predicate in (
            ('title', DCT.title),
            ('notes', DCT.description),
            ('url', DCAT.landingPage),
            ('version', OWL.versionInfo),
        ):
            value = self._object_value(dataset_ref, predicate)
            if value:
                dataset_dict[key] = value

        if not dataset_dict.get('version'):
            # adms:version was supported on the first version of the DCAT-AP
            value = self._object_value(dataset_ref, ADMS.version)
            if value:
                dataset_dict['version'] = value

        # Tags
        # replace munge_tag to noop if there's no need to clean tags
        do_clean = toolkit.asbool(config.get(DCAT_CLEAN_TAGS, False))
        tags_val = [
            munge_tag(tag) if do_clean else tag for tag in self._keywords(dataset_ref)
        ]
        tags = [{'name': tag} for tag in tags_val]
        dataset_dict['tags'] = tags

        # Extras

        #  Simple values
        for key, predicate in (
            ('issued', DCT.issued),
            ('modified', DCT.modified),
            ('identifier', DCT.identifier),
            ('version_notes', ADMS.versionNotes),
            # ('update_frequency', DCT.accrualPeriodicity),
            ('access_rights', DCT.accessRights),
            ('provenance', DCT.provenance),
            ('dcat_type', DCT.type),
            ('landing_page', DCAT.landingPage),
        ):
            value = self._object_value(dataset_ref, predicate)
            if value:
                dataset_dict['extras'].append({'key': key, 'value': value})

        #  Lists
        for (
            key,
            predicate,
        ) in (
            ('language', DCT.language),
            ('data_themes', DCAT.theme),
            ('alternate_identifier', ADMS.identifier),
            ('conforms_to', DCT.conformsTo),
            ('documentation', FOAF.page),
            ('related_resource', DCT.relation),
            ('has_version', DCT.hasVersion),
            ('is_version_of', DCT.isVersionOf),
            ('source', DCT.source),
            ('sample', ADMS.sample),
        ):
            values = self._object_value_list(dataset_ref, predicate)
            if values:
                dataset_dict['extras'].append({'key': key, 'value': json.dumps(values)})

        # Contact details
        contact = self._contact_details(dataset_ref, DCAT.contactPoint)
        if not contact:
            # adms:contactPoint was supported on the first version of DCAT-AP
            contact = self._contact_details(dataset_ref, ADMS.contactPoint)

        if contact:
            for key in ('uri', 'name', 'email'):
                if contact.get(key):
                    dataset_dict['extras'].append(
                        {'key': 'contact_{0}'.format(key), 'value': contact.get(key)}
                    )

        # Publisher
        publisher = self._publisher(dataset_ref, DCT.publisher)
        for key in ('uri', 'name', 'email', 'url', 'type'):
            if publisher.get(key):
                dataset_dict['extras'].append(
                    {'key': 'publisher_{0}'.format(key), 'value': publisher.get(key)}
                )

        # Temporal
        start, end = self._time_interval(dataset_ref, DCT.temporal)
        if start:
            dataset_dict['extras'].append({'key': 'temporal_start', 'value': start})
        if end:
            dataset_dict['extras'].append({'key': 'temporal_end', 'value': end})

        # Spatial
        spatial = self._spatial(dataset_ref, DCT.spatial)
        for key in ('uri', 'text', 'geom'):
            if spatial.get(key):
                dataset_dict['extras'].append(
                    {
                        'key': 'spatial_{0}'.format(key)
                        if key != 'geom'
                        else 'spatial',
                        'value': spatial.get(key),
                    }
                )

        # Dataset URI (explicitly show the missing ones)
        dataset_uri = (
            unicode(dataset_ref) if isinstance(dataset_ref, rdflib.term.URIRef) else ''
        )
        dataset_dict['extras'].append({'key': 'uri', 'value': dataset_uri})

        # License
        if 'license_id' not in dataset_dict:
            dataset_dict['license_id'] = self._license(dataset_ref)

        # Source Catalog
        if toolkit.asbool(config.get(DCAT_EXPOSE_SUBCATALOGS, False)):
            catalog_src = self._get_source_catalog(dataset_ref)
            if catalog_src is not None:
                src_data = self._extract_catalog_dict(catalog_src)
                dataset_dict['extras'].extend(src_data)

        # Resources
        for distribution in self._distributions(dataset_ref):
            resource_dict = {}

            #  Simple values
            for key, predicate in (
                ('name', DCT.title),
                ('description', DCT.description),
                ('access_url', DCAT.accessURL),
                ('download_url', DCAT.downloadURL),
                ('issued', DC.issued),
                ('modified', DC.modified),
                ('status', ADMS.status),
                ('rights', DCT.rights),
                ('license', DCT.license),
            ):
                value = self._object_value(distribution, predicate)
                if value:
                    resource_dict[key] = value

            resource_dict['url'] = self._object_value(
                distribution, DCAT.downloadURL
            ) or self._object_value(distribution, DCAT.accessURL)

            #  Lists
            for key, predicate in (
                ('language', DCT.language),
                ('documentation', FOAF.page),
                ('conforms_to', DCT.conformsTo),
            ):
                values = self._object_value_list(distribution, predicate)
                if values:
                    resource_dict[key] = json.dumps(values)

            # Format and media type
            normalize_ckan_format = config.get(
                'ckanext.dcat.normalize_ckan_format', True
            )
            imt, label = self._distribution_format(distribution, normalize_ckan_format)

            if imt:
                resource_dict['mimetype'] = imt

            if label:
                resource_dict['format'] = label
            elif imt:
                resource_dict['format'] = imt

            # Size
            size = self._object_value_int(distribution, DCAT.byteSize)
            if size is not None:
                resource_dict['size'] = size

            # Checksum
            for checksum in self.g.objects(distribution, SPDX.checksum):
                algorithm = self._object_value(checksum, SPDX.algorithm)
                checksum_value = self._object_value(checksum, SPDX.checksumValue)
                if algorithm:
                    resource_dict['hash_algorithm'] = algorithm
                if checksum_value:
                    resource_dict['hash'] = checksum_value

            # Distribution URI (explicitly show the missing ones)
            resource_dict['uri'] = (
                unicode(distribution)
                if isinstance(distribution, rdflib.term.URIRef)
                else ''
            )

            dataset_dict['resources'].append(resource_dict)

        if self.compatibility_mode:
            # Tweak the resulting dict to make it compatible with previous
            # versions of the ckanext-dcat parsers
            for extra in dataset_dict['extras']:
                if extra['key'] in (
                    'issued',
                    'modified',
                    'publisher_name',
                    'publisher_email',
                ):
                    extra['key'] = 'dcat_' + extra['key']

                if extra['key'] == 'language':
                    extra['value'] = ','.join(sorted(json.loads(extra['value'])))

        return dataset_dict

    def graph_from_dataset(self, dataset_dict, dataset_ref):
        g = self.g

        for prefix, namespace in namespaces.iteritems():
            g.bind(prefix, namespace)

        g.add((dataset_ref, RDF.type, DCAT.Dataset))

        translated_titles = dataset_dict.get('title_translated')

        if translated_titles:
            for lang, title in translated_titles.iteritems():
                title = title.strip()
                if title:
                    g.add((dataset_ref, DCT.title, Literal(title, lang=lang)))

        translated_descriptions = dataset_dict.get('notes_translated')

        if translated_descriptions:
            for lang, description in translated_descriptions.iteritems():
                description = description.strip()
                if description:
                    g.add((dataset_ref, DCT.description, Literal(description, lang=lang)))

        # Basic fields
        items = [
            ('url', DCAT.landingPage, None, URIRef),
            ('identifier', DCT.identifier, ['guid', 'id'], Literal),
            ('version', OWL.versionInfo, ['dcat_version'], Literal),
            ('version_notes', ADMS.versionNotes, None, Literal),
            ('dcat_type', DCT.type, None, Literal),
            ('provenance', DCT.provenance, None, Literal),
        ]
        self._add_triples_from_dict(dataset_dict, dataset_ref, items)

        # Tags
        for tag in dataset_dict.get('tags', []):
            g.add((dataset_ref, DCAT.keyword, Literal(tag['name'])))

        # Dates
        items = [
            ('issued', DC.issued, ['metadata_created'], Literal),
            ('modified', DC.modified, ['metadata_modified'], Literal),
        ]
        self._add_date_triples_from_dict(dataset_dict, dataset_ref, items)

        # Update frequency
        update_frequency = self._get_dataset_value(dataset_dict, 'update_frequency')
        dcat_frequencies = oddk_helpers.frequencies_from_file()

        if update_frequency and update_frequency in dcat_frequencies:
            frequency_uri = URIRef(FREQUENCY_BASE_URI + update_frequency)
            g.add((dataset_ref, DCT.accrualPeriodicity, frequency_uri))

        # Access rights
        access_rights = self._get_dataset_value(dataset_dict, 'access_rights')

        if access_rights:
            access_rights_uri = URIRef(ACCESS_RIGHTS_URI + access_rights)
            g.add((dataset_ref, DCT.accessRights, access_rights_uri))
            g.add((access_rights_uri, RDF.type, DCT.RightsStatement))

        # Documentation
        documentation = self._get_dataset_value(dataset_dict, 'documentation')

        if documentation:
            documentation_url = (
                documentation
                if 'http' in documentation
                else '{}/dataset/{}/documentation/{}'.format(
                    config.get('ckan.site_url'),
                    dataset_dict.get('name'),
                    dataset_dict.get('id'),
                )
            )
            documentation_uri = URIRef(documentation_url)
            g.add((documentation_uri, RDF.type, FOAF.Document))
            g.add((dataset_ref, FOAF.page, documentation_uri))

        #  Lists
        items = [
            ('alternate_identifier', ADMS.identifier, None, Literal),
            ('related_resource', DCT.relation, None, URIRefOrLiteral),
            ('has_version', DCT.hasVersion, None, URIRefOrLiteral),
            ('is_version_of', DCT.isVersionOf, None, URIRefOrLiteral),
            ('source', DCT.source, None, Literal),
            ('sample', ADMS.sample, None, Literal),
        ]
        self._add_list_triples_from_dict(dataset_dict, dataset_ref, items)

        # Data theme
        dataset_groups = dataset_dict.get('groups', [])

        for group in dataset_groups:
            group_name = group['name']

            if group_name in GROUP_TO_THEME:
                theme_name = GROUP_TO_THEME[group_name]['name']
                theme_uri = URIRef(DATA_THEME_BASE_URI + theme_name)

                g.add((theme_uri, RDF.type, SKOS.Concept))
                g.add(
                    (
                        theme_uri,
                        SKOS.prefLabel,
                        Literal(DATA_THEME_LABELS[theme_name]['da'], lang='da'),
                    )
                )
                g.add(
                    (
                        theme_uri,
                        SKOS.prefLabel,
                        Literal(DATA_THEME_LABELS[theme_name]['en'], lang='en'),
                    )
                )
                g.add(
                    (
                        theme_uri,
                        SKOS.prefLabel,
                        Literal(DATA_THEME_LABELS[theme_name]['fr'], lang='fr'),
                    )
                )
                g.add((dataset_ref, DCAT.theme, theme_uri))

        # Conforms to
        g.add((dataset_ref, DC.conformsTo, URIRef(CONFORMS_TO)))

        # Language
        titles_translated = dataset_dict.get('title_translated')
        languages = []

        if titles_translated:
            for lang, title in titles_translated.iteritems():
                if title:
                    languages.append(lang)

        language_conversion = {
            'en': 'ENG',
            'da': 'DAN',
            'fr': 'FRE',
        }

        for lang in languages:
            if lang in language_conversion:
                g.add(
                    (
                        dataset_ref,
                        DCT.language,
                        URIRef(LANGUAGE_BASE_URI + language_conversion[lang]),
                    )
                )

        # Contact details
        if any(
            [
                self._get_dataset_value(dataset_dict, 'contact_uri'),
                self._get_dataset_value(dataset_dict, 'contact_name'),
                self._get_dataset_value(dataset_dict, 'contact_email'),
                self._get_dataset_value(dataset_dict, 'maintainer'),
                self._get_dataset_value(dataset_dict, 'maintainer_email'),
                self._get_dataset_value(dataset_dict, 'author'),
                self._get_dataset_value(dataset_dict, 'author_email'),
            ]
        ):
            contact_uri = self._get_dataset_value(dataset_dict, 'contact_uri')
            if contact_uri:
                contact_details = CleanedURIRef(contact_uri)
            else:
                contact_details = BNode()

            g.add((contact_details, RDF.type, VCARD.Kind))
            g.add((dataset_ref, DCAT.contactPoint, contact_details))

            self._add_triple_from_dict(
                dataset_dict,
                contact_details,
                VCARD.fn,
                'contact_name',
                ['maintainer', 'author'],
            )
            # Add mail address as URIRef, and ensure it has a mailto: prefix
            self._add_triple_from_dict(
                dataset_dict,
                contact_details,
                VCARD.hasEmail,
                'contact_email',
                ['maintainer_email', 'author_email'],
                _type=URIRef,
                value_modifier=self._add_mailto,
            )

        # Publisher
        if any(
            [
                self._get_dataset_value(dataset_dict, 'publisher_uri'),
                self._get_dataset_value(dataset_dict, 'publisher_name'),
                dataset_dict.get('organization'),
            ]
        ):
            publisher_uri = publisher_uri_from_dataset_dict(dataset_dict)
            if publisher_uri:
                publisher_details = CleanedURIRef(publisher_uri)
            else:
                # No organization nor publisher_uri
                publisher_details = BNode()

            g.add((publisher_details, RDF.type, FOAF.Agent))
            g.add((dataset_ref, DCT.publisher, publisher_details))

            publisher_name = self._get_dataset_value(dataset_dict, 'publisher_name')
            if not publisher_name and dataset_dict.get('organization'):
                publisher_name = dataset_dict['organization']['title']

            g.add((publisher_details, FOAF.name, Literal(publisher_name)))
            # TODO: It would make sense to fallback these to organization
            # fields but they are not in the default schema and the
            # `organization` object in the dataset_dict does not include
            # custom fields
            items = [
                ('publisher_email', FOAF.mbox, None, Literal),
                ('publisher_url', FOAF.homepage, None, URIRef),
                ('publisher_type', DCT.type, None, URIRefOrLiteral),
            ]

            self._add_triples_from_dict(dataset_dict, publisher_details, items)

        # Temporal
        start = self._get_dataset_value(dataset_dict, 'temporal_start')
        end = self._get_dataset_value(dataset_dict, 'temporal_end')
        if start or end:
            temporal_extent = BNode()

            g.add((temporal_extent, RDF.type, DCT.PeriodOfTime))
            if start:
                self._add_date_triple(temporal_extent, SCHEMA.startDate, start)
            if end:
                self._add_date_triple(temporal_extent, SCHEMA.endDate, end)
            g.add((dataset_ref, DCT.temporal, temporal_extent))

        # Spatial
        spatial_uri = self._get_dataset_value(dataset_dict, 'spatial_uri')
        spatial_text = self._get_dataset_value(dataset_dict, 'spatial_text')
        spatial_geom = self._get_dataset_value(dataset_dict, 'spatial')

        if spatial_uri or spatial_text or spatial_geom:
            if spatial_uri:
                spatial_ref = CleanedURIRef(spatial_uri)
            else:
                spatial_ref = BNode()

            g.add((spatial_ref, RDF.type, DCT.Location))
            g.add((dataset_ref, DCT.spatial, spatial_ref))

            if spatial_text:
                g.add((spatial_ref, SKOS.prefLabel, Literal(spatial_text)))

            if spatial_geom:
                # GeoJSON
                g.add(
                    (
                        spatial_ref,
                        LOCN.geometry,
                        Literal(spatial_geom, datatype=GEOJSON_IMT),
                    )
                )
                # WKT, because GeoDCAT-AP says so
                try:
                    g.add(
                        (
                            spatial_ref,
                            LOCN.geometry,
                            Literal(
                                wkt.dumps(json.loads(spatial_geom), decimals=4),
                                datatype=GSP.wktLiteral,
                            ),
                        )
                    )
                except (TypeError, ValueError, InvalidGeoJSONException):
                    pass

        # Resources
        for resource_dict in dataset_dict.get('resources', []):
            # Format
            mimetype = resource_dict.get('mimetype')
            fmt = resource_dict.get('format')

            # IANA media types (either URI or Literal) should be mapped as mediaType.
            # In case format is available and mimetype is not set or identical to format,
            # check which type is appropriate.
            if fmt and (not mimetype or mimetype == fmt):
                if (
                    'iana.org/assignments/media-types' in fmt
                    or not fmt.startswith('http')
                    and '/' in fmt
                ):
                    # output format value as dcat:mediaType instead of dct:format
                    mimetype = fmt
                    fmt = None
                else:
                    # Use dct:format
                    mimetype = None

            dcat_formats = oddk_helpers.formats_from_file()

            if fmt and fmt in dcat_formats:
                distribution = CleanedURIRef(
                    '{}/dataset/{}/resource/{}'.format(
                        config.get('ckan.site_url'),
                        dataset_dict.get('name'),
                        resource_dict.get('id'),
                    )
                )

                g.add((dataset_ref, DCAT.distribution, distribution))

                g.add((distribution, RDF.type, DCAT.Distribution))

                #  Simple values
                items = [
                    ('name', DCT.title, None, Literal),
                    ('description', DCT.description, None, Literal),
                    ('status', ADMS.status, None, URIRefOrLiteral),
                    ('rights', DCT.rights, None, URIRefOrLiteral),
                    ('access_url', DCAT.accessURL, None, URIRef),
                    ('download_url', DCAT.downloadURL, None, URIRef),
                ]

                self._add_triples_from_dict(resource_dict, distribution, items)

                # License (uses SKOS concept)
                license_id = resource_dict.get('license_id')
                skos_licenses = {
                    'cco': 'CC0',
                    'cc-by': 'CC_BY',
                    'cc-bysa': 'CC_BYSA',
                    'PDDL-1.0': 'ODC_PDDL',
                    'ODbL-1.0': 'ODC_BL',
                    'ODC-BY-1.0': 'ODC_BY',
                    'CC0-1.0': 'CC0',
                    'CC-BY-4.0': 'CC_BY_4_0',
                    'CC-BY-SA-4.0': 'CC_BYSA_4_0',
                    'GFDL-1.3-no-cover-texts-no-invariant-sections': 'GNU_FDL_1_3',
                    'OGL-UK-2.0': 'OGL_NC',
                    'CC-BY-NC-4.0': 'CC_BYNC_4_0',
                }

                if license_id and license_id in skos_licenses:
                    skos_license = skos_licenses[license_id]
                    license_uri = URIRef(LICENSES_BASE_URI + skos_license)
                    g.add((license_uri, RDF.type, SKOS.Concept))
                    g.add((license_uri, RDF.type, DCT.LicenseDocument))
                    g.add(
                        (
                            license_uri,
                            SKOS.prefLabel,
                            Literal(LICENSES[skos_license]['label']['dan'], lang='da'),
                        )
                    )
                    g.add(
                        (
                            license_uri,
                            SKOS.prefLabel,
                            Literal(LICENSES[skos_license]['label']['eng'], lang='en'),
                        )
                    )
                    g.add(
                        (
                            license_uri,
                            SKOS.prefLabel,
                            Literal(LICENSES[skos_license]['label']['fra'], lang='fr'),
                        )
                    )
                    g.add((distribution, DCT.license, license_uri))

                # Availability type (uses SKOS concept)
                planned_availability = resource_dict.get('planned_availability')

                if planned_availability:
                    availability_uri = URIRef(
                        PLANNED_AVAILABILITY_URI + planned_availability
                    )
                    g.add((availability_uri, RDF.type, SKOS.Concept))
                    g.add(
                        (
                            availability_uri,
                            SKOS.prefLabel,
                            Literal(
                                PLANNED_AVAILABILITY_LABELS[planned_availability]['da'],
                                lang='da',
                            ),
                        )
                    )
                    g.add(
                        (
                            availability_uri,
                            SKOS.prefLabel,
                            Literal(
                                PLANNED_AVAILABILITY_LABELS[planned_availability]['en'],
                                lang='en',
                            ),
                        )
                    )
                    g.add(
                        (
                            availability_uri,
                            SKOS.prefLabel,
                            Literal(
                                PLANNED_AVAILABILITY_LABELS[planned_availability]['fr'],
                                lang='fr',
                            ),
                        )
                    )
                    g.add((distribution, DCAT_AP['availability'], availability_uri))

                #  Lists
                items = [
                    ('documentation', FOAF.page, None, URIRefOrLiteral),
                    ('language', DCT.language, None, URIRefOrLiteral),
                ]
                self._add_list_triples_from_dict(resource_dict, distribution, items)

                # Conforms to
                g.add((distribution, DC.conformsTo, URIRef(CONFORMS_TO)))

                if fmt:
                    fmt_uri = URIRef(FORMAT_BASE_URI + fmt)
                    g.add((distribution, DCT['format'], fmt_uri))

                # URL fallback and old behavior
                url = resource_dict.get('url')
                download_url = resource_dict.get('download_url')
                access_url = resource_dict.get('access_url')
                # Use url as fallback for access_url if access_url is not set and download_url is not equal
                if url and not access_url:
                    if (not download_url) or (download_url and url != download_url):
                        self._add_triple_from_dict(
                            resource_dict,
                            distribution,
                            DCAT.accessURL,
                            'url',
                            _type=URIRef,
                        )

                # Dates
                items = [
                    ('issued', DC.issued, None, Literal),
                    ('modified', DC.modified, None, Literal),
                ]

                self._add_date_triples_from_dict(resource_dict, distribution, items)

                # Numbers
                if resource_dict.get('size'):
                    try:
                        g.add(
                            (
                                distribution,
                                DCAT.byteSize,
                                Literal(
                                    float(resource_dict['size']), datatype=XSD.decimal
                                ),
                            )
                        )
                    except (ValueError, TypeError):
                        g.add(
                            (
                                distribution,
                                DCAT.byteSize,
                                Literal(resource_dict['size']),
                            )
                        )
                # Checksum
                if resource_dict.get('hash'):
                    checksum = BNode()
                    g.add((checksum, RDF.type, SPDX.Checksum))
                    g.add(
                        (
                            checksum,
                            SPDX.checksumValue,
                            Literal(resource_dict['hash'], datatype=XSD.hexBinary),
                        )
                    )

                    if resource_dict.get('hash_algorithm'):
                        g.add(
                            (
                                checksum,
                                SPDX.algorithm,
                                URIRefOrLiteral(resource_dict['hash_algorithm']),
                            )
                        )

                    g.add((distribution, SPDX.checksum, checksum))

    def graph_from_catalog(self, catalog_dict, catalog_ref):
        g = self.g

        for prefix, namespace in namespaces.iteritems():
            g.bind(prefix, namespace)

        g.add((catalog_ref, RDF.type, DCAT.Catalog))

        # Basic fields
        items = [
            ('title', DCT.title, config.get('ckan.site_title'), Literal),
            (
                'description',
                DCT.description,
                config.get('ckan.site_description') or 'Open Data DK',
                Literal,
            ),
            ('homepage', FOAF.homepage, config.get('ckan.site_url'), URIRef),
        ]

        # Languages
        languages = [
            lang.split('_')[0]
            for lang in config.get('ckan.locales_offered', 'en').split()
        ]
        language_conversion = {
            'en': 'ENG',
            'da': 'DAN',
            'fr': 'FRE',
        }
        items.extend(
            [
                ('language', DCT.language, language_conversion[lang], URIRefOrLiteral)
                for lang in languages
                if lang in language_conversion
            ]
        )

        # Spatial
        spatial = BNode()
        g.add((spatial, RDF.type, DCT.Location))
        g.add((catalog_ref, DCT.spatial, spatial))
        g.add((spatial, SKOS.prefLabel, Literal('Danmark', lang='da')))
        g.add((spatial, SKOS.prefLabel, Literal('Denmark', lang='en')))
        g.add((spatial, SKOS.prefLabel, Literal('Danemark', lang='fr')))
        g.add((spatial, LOCN.geometry, Literal('Denmark', datatype=GEOJSON_IMT)))

        # Theme Taxonomy
        theme_taxonomy_uri = URIRef(DATA_THEME_BASE_URI)
        g.add((catalog_ref, DCAT.themeTaxonomy, theme_taxonomy_uri))
        g.add((theme_taxonomy_uri, RDF.type, SKOS.ConceptScheme))
        g.add((theme_taxonomy_uri, DCT.title, Literal('emneklassifikation', lang='da')))
        g.add((theme_taxonomy_uri, DCT.title, Literal('theme taxonomy', lang='en')))
        g.add((theme_taxonomy_uri, DCT.title, Literal('taxonomie des thèmes', lang='fr')))

        for item in items:
            key, predicate, fallback, _type = item

            if catalog_dict:
                value = catalog_dict.get(key, fallback)
            else:
                value = fallback

            if key == 'language':
                value = URIRef(LANGUAGE_BASE_URI + value)
            if key == 'homepage':
                homepage_uri = URIRef(value)
                g.add((homepage_uri, RDF.type, FOAF.Document))
            if value:
                g.add((catalog_ref, predicate, _type(value)))

        publisher_uri = URIRef(config.get('ckan.site_url') + '/hvad-er-open-data-dk')
        g.add((publisher_uri, RDF.type, FOAF.Agent))
        g.add((publisher_uri, FOAF.name, Literal('Open Data DK')))
        g.add((catalog_ref, DCT.publisher, publisher_uri))

        # Dates
        modified = self._last_catalog_modification()

        if modified:
            self._add_date_triple(catalog_ref, DC.modified, modified)
