from importlib.metadata import version as pkg_version

project = "suite"
author = "Sheldon McGrandle"
release = pkg_version("suite-cli")

extensions = ["myst_parser", "sphinx_click"]
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

root_doc = "cli"
exclude_patterns = ["_build"]

man_pages = [
    (
        "cli",
        "suite",
        "track the git status of every application in your suite",
        ["Sheldon McGrandle"],
        1,
    ),
]
