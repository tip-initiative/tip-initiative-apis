import pickle
import re
import sys
from copy import copy
from pathlib import Path
from typing import List, Any, Union, Dict, Iterable

import attr
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import SingleQuotedScalarString, FoldedScalarString

# Maximum width of line in YAML output
PAGE_WIDTH = 99

# If modifying these scopes, delete the file token.pickle.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# The ID and range of a sample spreadsheet.
SHEET_ID = "1J1v6ol6hSEWSlUPF4ZPMq-TMc_See3ZprvwjS_HqZic"

# Directory where the schemas live.
SCHEMAS: Path = Path(__file__).absolute().parents[1] / "endpoints" / "schemas"


@attr.s(frozen=True, slots=True)
class Sheet:
    schema: str = attr.ib()
    name: str = attr.ib()
    start_row: int = attr.ib()
    version: str = attr.ib()
    title: str = attr.ib()
    description: str = attr.ib()

    @property
    def range(self) -> str:
        """Pull data from this Sheet range.

        We start at start_row and only go through column F.
        """
        return f"{self.name}!A{self.start_row}:F"


def clean_description(description: str):
    """Remove duplicate / unwanted extra spaces from description."""
    r = " ".join(description.split())
    r = re.sub(r"\(\s+", "(", r)
    r = re.sub(r"\s+\)", ")", r)
    if len(r) > PAGE_WIDTH:
        return FoldedScalarString(r)
    else:
        return str(r)


@attr.s(frozen=False, slots=True)
class ModelRow:
    name: str = attr.ib()
    required: str = attr.ib()
    type: str = attr.ib()
    data_type: str = attr.ib(factory=str)
    enum_values: str = attr.ib(factory=str)
    description: str = attr.ib(factory=str, converter=clean_description)
    sheet: Sheet = attr.ib(default=None)

    @classmethod
    def from_list(cls, row: List[str]):
        return cls(*[n.strip() for n in row])

    @property
    def is_required(self) -> bool:
        return self.required == "Required"

    @property
    def is_deleted(self) -> bool:
        return self.required.upper() == "DELETED"

    def parse(self, line_num: int = 0) -> Any:
        data_type = self.data_type.strip().lower()

        assert "array" not in data_type, self
        assert self.data_type, f"{line_num + 1}: {self}"

        if "string" == data_type:
            r = self.parse_string()

        elif "enum" == data_type:
            r = self.parse_enum()

        elif "integer" == data_type:
            r = self.parse_int()

        elif "date" == data_type:
            r = self.parse_date()

        elif "time" == data_type:
            r = self.parse_time()

        elif "float" == data_type:
            r = self.parse_float()

        elif "boolean" == data_type:
            r = self.parse_bool()

        elif "email" == data_type:
            r = self.parse_email()

        elif data_type.startswith("enum"):
            r = self.parse_enum()

        elif "," in data_type:
            r = self.parse_many()

        else:
            r = self.parse_ref()

        if "array" in self.type.lower():
            try:
                real_type = {"type": r["type"]}
            except KeyError:
                real_type = {"$ref": r["$ref"]}
            r = {"type": "array", "items": real_type}

        rr = {}

        if self.description:
            rr["description"] = self.description

        rr.update(r)

        return {self.name: rr}

    def parse_ref(self) -> dict:
        self.description = ""
        prefix = "#" if self.sheet.name == "Common Models" else "commonSchemas.yaml#"
        ref = f"{prefix}/components/schemas/{self.data_type.strip()}"
        return {"$ref": SingleQuotedScalarString(ref)}

    @staticmethod
    def parse_string() -> dict:
        return {"type": "string"}

    def parse_enum(self):
        vals = [n.strip() for n in self.enum_values.split(",")]
        return {"type": "string", "enum": vals}

    @staticmethod
    def parse_int():
        return {"type": "integer"}

    @staticmethod
    def parse_date():
        return {"type": "string", "format": "date"}

    @staticmethod
    def parse_time():
        return {"type": "string", "format": "date-time"}

    @staticmethod
    def parse_float():
        return {"type": "number", "format": "float"}

    @staticmethod
    def parse_bool():
        return {"type": "boolean"}

    @staticmethod
    def parse_email():
        return {"type": "string", "format": "email"}

    def parse_many(self):
        types = []
        for v in [n.strip() for n in self.data_type.split(",")]:
            other = copy(self)
            other.data_type = v
            other.description = ""
            r = other.parse()
            types.append(r[other.name])
        return {"oneOf": types}


# We use the "complicated" method of construction here because it makes dict keep the insert order,
# whereas we would get any-order-is-fine behavior with traditional construct.
def header(version: str, title: str, description: str) -> dict:
    return dict(
        [
            ("openapi", "3.0.0"),
            (
                "info",
                dict(
                    [
                        ("version", version),
                        ("title", title),
                        ("description", description),
                        ("termsOfService", "http://placeholderdomain.io/terms/"),
                        (
                            "contact",
                            dict(
                                [
                                    ("name", "TIP Initiative"),
                                    ("email", "tipinitiative@frontrowadvisory.com"),
                                    ("url", "http://placeholderdomain.io"),
                                ]
                            ),
                        ),
                        (
                            "license",
                            dict(
                                [("name", "MIT"), ("url", "https://opensource.org/licenses/MIT")]
                            ),
                        ),
                    ]
                ),
            ),
            ("paths", {}),
        ]
    )


def google_creds():
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    token_pickle = Path(__file__).with_name("token.pickle")
    if token_pickle.exists():
        with token_pickle.open("rb") as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds_json = Path(__file__).with_name("credentials.json")
            flow = InstalledAppFlow.from_client_secrets_file(creds_json, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with token_pickle.open("wb") as token:
            pickle.dump(creds, token)
    return creds


def main(sheets: Iterable[Sheet]):
    service = build("sheets", "v4", credentials=google_creds())

    sheet: Sheet
    for sheet in sheets:

        # This is the schema output file
        out_file = SCHEMAS / sheet.schema

        # Call the Sheets API
        svc = service.spreadsheets()
        result = svc.values().get(spreadsheetId=SHEET_ID, range=sheet.range).execute()
        values = result.get("values", [])
        if not values:
            return

        schemas: Dict[str, Dict[str, Union[List[str], Dict[str]]]] = {}
        klass: str = ""

        c: int
        v: List[str]
        for c, v in enumerate(values):
            # Skip the row if the "name" field is empty
            row_num = c + sheet.start_row
            try:
                row: ModelRow = ModelRow.from_list(v)
                row.sheet = sheet
            except TypeError:
                print(f"WARNING: Stopped at [{sheet.name} -> Row {row_num}]: {v}")
                break

            if row.type == "TypeDef":
                klass = row.name
                schemas[klass] = {"properties": {}}

                if row.data_type.lower() == "enum":
                    r = row.parse_enum()
                    schemas[klass] = r

                continue

            if not klass:
                continue

            r = row.parse(c)
            if r:
                if row.is_deleted:
                    print(
                        f"INFO: {row.name} at [{sheet.name} -> Row {row_num}] is marked DELETED."
                    )
                    continue

                schemas[klass]["properties"].update(r)

                if row.is_required:
                    try:
                        schemas[klass]["required"].append(row.name)
                    except KeyError:
                        schemas[klass]["required"] = [row.name]

        content = header(sheet.version, sheet.title, sheet.description)
        content["components"] = {"schemas": schemas}
        with out_file.open(mode="wt") as fp:
            with YAML(output=fp) as yaml:
                yaml.indent(mapping=2, sequence=4, offset=2)
                yaml.width = PAGE_WIDTH
                yaml.dump(content)
                print(f"INFO: Updated {out_file}")


def re_dump(file_path: Union[Path, str]):
    """Open and reformat an existing YAML file."""
    file_: Path = Path(file_path)
    xyz = YAML(typ="safe", pure=True).load(file_.open().read())

    with YAML(output=sys.stdout) as yaml:
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.width = PAGE_WIDTH
        yaml.dump(xyz)


SHEETS: List[Sheet] = [
    Sheet(
        "commonSchemas.yaml",
        "Common Models",
        6,
        "4.2.0",
        "Common Schemas",
        "Common Schemas, based on TIP 4.0 documentation",
    ),
    Sheet(
        "logTimesSchemas.yaml",
        "Seller/ Logtimes",
        11,
        "1.2.0",
        "logTimes Schemas",
        "logTimes Schemas, based on TIP 4.0 documentation",
    ),
    # Sheet(
    #     "inventoryAvailsSchemas.yaml",
    #     "Seller/ InventoryAvails",
    #     11,
    #     "0.0.1",
    #     "Inventory Avails Schemas",
    #     "Inventory Avails Schemas, based on TIP 4.0.0 documentation",
    # ),
    Sheet(
        "invoiceSchemas.yaml",
        "Seller/ Invoice",
        11,
        "1.2.0",
        "Invoice Schema",
        "Invoice Schema, Based on TIP 4.0 Working Draft",
    ),
    Sheet(
        "commercialInstructionSchemas.yaml",
        "Buyer/ CommercialInstructions",
        11,
        "1.2.0",
        "Commercial Instructions Schema",
        "Commercial Instructions Schema, Based on TIP 4.0 Working Draft",
    ),
]


if __name__ == "__main__":
    main(SHEETS)
