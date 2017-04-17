from setuptools import setup

setup(
    name='melbalabs_notify',
    packages=['melbalabs.notify'],
    include_package_data=True,
    zip_safe=False,
    use_scm_version=True,
    setup_requires=['setuptools_scm'],

)
