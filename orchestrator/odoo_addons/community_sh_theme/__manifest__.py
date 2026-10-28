{
    'name': 'Community SH Theme',
    'summary': 'Clean backend look and an app-grid home screen for Odoo Community (15 to 20)',
    'description': 'An original theme, inspired by the look of recent Odoo versions: light top bar, form sheets as '
                   'cards, rounded controls and a home screen with the apps as icons. It does not include any '
                   'Odoo Enterprise code or assets.',
    'version': '1.0',
    'category': 'Themes/Backend',
    'license': 'LGPL-3',
    'author': 'Community SH',
    'depends': ['web'],
    'data': ['data/home.xml'],
    'assets': {
        'web.assets_backend': ['community_sh_theme/static/src/scss/theme.scss'],
    },
    'post_init_hook': 'set_home_screen',
    'uninstall_hook': 'reset_home_screen',
    'installable': True,
    'application': True,
}
