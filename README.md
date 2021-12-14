# Overview

Worknight is unoficial python library and CLI tool `wn` to access and interact with WorkDay HR. Created because I didn't get API access.


## Initial configuration

Install [pipx](https://pipx.pypa.io/), e.g. in Fedora:
```bash
sudo dnf install -y pipx
```

Use pipx to install the CLI tool from the repository:

```bash
pipx install git+https://github.com/pbabinca/worknight

```

Set company-specific top-level URL of the WorkDay:

```bash
wn config set home_url https://wd5.myworkday.com/example/d/home.htmld
```

where you replace "example" with the correct value.

Set browser-specific configuration, e.g. with Kerberos of domain "example.com":

```bash
wn config set --parent browser_configuration --parent firefox --parent preferences network.negotiate-auth.trusted-uris .example.com
```

Optionally, if you don't use the default "en_US" locale, you should set a language. Pick appropriate one from the [dateparser languages](https://dateparser.readthedocs.io/en/latest/supported_locales.html) and (for e.g. "cs") run:
```bash
wn config set --parent account_preferences language cs
```


## Usage

Use `wn` CLI. E.g. to explore options:

```bash
wn --help
```

E.g. to list absences of the current month:

```bash
wn absence list
```

## Contact

Author: Pavol Babinčák <pbabinca@redhat.com>

Original Git Repository: <https://github.com/pbabinca/worknight>


## License

This library is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation; either version 3 of the License, or (at your option) any later version.

This library is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this library; if not, see <http://www.gnu.org/licenses/>.
