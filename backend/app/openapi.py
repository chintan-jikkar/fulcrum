"""Print the API's OpenAPI schema. `npm run gen:api` in web/ turns it into the TypeScript client."""

import json

from app.main import app

if __name__ == "__main__":
    print(json.dumps(app.openapi(), indent=2, sort_keys=True))
