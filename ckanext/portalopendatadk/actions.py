import logging
import markdown
import html2text

#from paste.deploy.converters import asbool

import ckan.logic as logic
import ckan.lib.dictization
import ckan.logic.action
import ckan.logic.schema
import ckan.lib.navl.dictization_functions
import ckan.lib.datapreview
import ckan.plugins.toolkit as toolkit

from ckan.common import _, config

# Define some shortcuts
# Ensure they are module-private so that they don't get loaded as available
# actions in the action API.
_get_action = logic.get_action
ValidationError = logic.ValidationError
NotFound = logic.NotFound

log = logging.getLogger(__name__)

DCAT_DATASET_FIELDS = [
    'title',
    'notes',
]


def translate_fields(context, data_dict):
    html_convert = html2text.HTML2Text()
    pkg_title = data_dict.get('title')
    pkg_notes = data_dict.get('notes', '')
    default_lang = config.get('ckan.locale_default', 'da').split('_')[0]

    data_dict['title_translated-{}'.format(default_lang)] = pkg_title
    data_dict['notes_translated-{}'.format(default_lang)] = (
        pkg_notes if pkg_notes else ''
    )

    languages_offered = config.get('ckan.locales_offered', 'en fr')
    languages = languages_offered.split()
    languages = [lang.split('_')[0] for lang in languages if lang != default_lang]

    for lang in languages:
        try:
            translation = _get_action('translate')(
                context,
                {
                    'input': {
                        'title': pkg_title,
                        'notes': markdown.markdown(pkg_notes),
                    },
                    'from': default_lang,
                    'to': lang,
                },
            )
            translation_title_output = translation['output'].get('title')
            translation_notes_output = translation['output'].get('notes')
            translation_outputs = {
                'title': translation_title_output,
                'notes': translation_notes_output,
            }

            for name, translation_output in list(translation_outputs.items()):
                if translation_output.startswith('\n\n'):
                    translation_outputs[name] = translation_output[2:]

                if translation_output.endswith('\n\n'):
                    translation_outputs[name] = translation_output[:-2]

            data_dict['title_translated-{}'.format(lang)] = translation_outputs['title']
            data_dict['notes_translated-{}'.format(lang)] = html_convert.handle(
                translation_outputs['notes']
            )

        except Exception as e:
            log.debug(
                'Unable to retrieve {} translation for {}: {}'.format(
                    lang, data_dict.get('name'), e
                )
            )
            data_dict['title_translated-{}'.format(lang)] = pkg_title
            data_dict['notes_translated-{}'.format(lang)] = pkg_notes

    existing_title_translations = data_dict.get('title_translated')
    existing_notes_translations = data_dict.get('notes_translated')

    if existing_title_translations:
        for lang, translation in list(existing_title_translations.items()):
            data_dict['title_translated'][lang] = data_dict[
                'title_translated-{}'.format(lang)
            ]

    if existing_notes_translations:
        for lang, translation in list(existing_notes_translations.items()):
            data_dict['notes_translated'][lang] = data_dict[
                'notes_translated-{}'.format(lang)
            ]

    return data_dict


@toolkit.chained_action
def package_create(up_func, context, data_dict):
    data_dict = translate_fields(context, data_dict)

    for extra in data_dict.get('extras', []):
        if extra.get('key') == 'contact_name' and not data_dict.get('author'):
            data_dict['author'] = extra['value']
        if extra.get('key') == 'contact_email' and not data_dict.get('author_email'):
            data_dict['author_email'] = extra['value']

    errors = {}

    if data_dict.get('data_directory') in [True, 'True']:
        for field in DCAT_DATASET_FIELDS:
            if not data_dict.get(field):
                errors[field] = [_('Missing value')]
    if errors:
        raise ValidationError(errors)

    documentation = data_dict.get("documentation")
    data_dict['url'] = documentation

    return up_func(context, data_dict)

@toolkit.side_effect_free
@toolkit.chained_action
def package_search(up_func, context, data_dict):
    search_results = up_func(context, data_dict)
    # Avoid returning datasets without notes when using package_search for DCAT
    if context.get('from_dcat'):
        search_results['results'] = [
            result
            for result in search_results['results']
            if all(
                [
                    result.get(field) not in [None, ''] and len(result.get(field)) > 0
                    for field in DCAT_DATASET_FIELDS
                ]
            )
        ]

    return search_results
