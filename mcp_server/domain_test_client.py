#!/usr/bin/env python3
"""
Test client for the Domain Checker MCP Server.

This script connects to the running domain-checker.py MCP server
and calls its tools to check for domain availability.

Prerequisites:
- The domain-checker.py server must be running.
- The required packages must be installed (pip install -r requirements.txt).

How to run the server (in one terminal):
1. Activate your virtual environment: `source venv/bin/activate`
2. Run the server: `python domain-checker.py`

How to run this client (in another terminal):
1. Activate your virtual environment: `source venv/bin/activate`
2. Run with a single domain:
   `python test_client.py --single google.com`
3. Run with multiple domains:
   `python test_client.py --multiple google.com my-awesome-new-startup.org`
4. List available tools:
   `python test_client.py --list-tools`
"""
import asyncio
import argparse
import logging
from fastmcp.client import Client

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mcp-client")

# The URL where the domain-checker.py MCP server is running
SERVER_URL = "https://do-remote-mcp-server-template-8cs8k.ondigitalocean.app/mcp/" # "http://localhost:8080/mcp"

async def main():
    """Main function to parse arguments and call the MCP server."""
    parser = argparse.ArgumentParser(
        description="Test client for the Domain Checker MCP server.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--single",
        metavar="DOMAIN",
        help="Check a single domain's availability."
    )
    parser.add_argument(
        "--multiple",
        nargs='+',
        metavar="DOMAIN",
        help="Check multiple domains' availability."
    )
    parser.add_argument(
        "--resource",
        metavar="DOMAIN",
        help="Test the domain://check/{domain} resource directly."
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List available tools from the server."
    )
    parser.add_argument(
        "--url",
        default=SERVER_URL,
        help=f"URL of the MCP server (default: {SERVER_URL})"
    )

    args = parser.parse_args()

    if not any([args.single, args.multiple, args.resource, args.list_tools]):
        logger.error("You must specify an action with --single, --multiple, --resource, or --list-tools.")
        parser.print_help()
        return

    try:
        async with Client(args.url) as client:
            logger.info(f"Connecting to MCP server at {args.url}")

            if args.list_tools:
                logger.info("Fetching available tools from the server...")
                tools_response = await client.list_tools()
                print("\n--- Available Tools ---")

                # The list_tools() method might return a ListToolsResult object (with a .tools attribute)
                # or a raw list of tools, depending on library version or server response.
                # This code handles both cases.
                actual_tools = []
                if hasattr(tools_response, 'tools') and tools_response.tools:
                    actual_tools = tools_response.tools
                elif isinstance(tools_response, list):
                    actual_tools = tools_response

                if actual_tools:
                    for tool in actual_tools:
                        print(f"  - Name: {tool.name}")
                        print(f"    Description: {tool.description.strip()}")
                        # The correct attribute is 'inputSchema', not 'parameters'.
                        if tool.inputSchema and tool.inputSchema.get("properties"):
                            print("    Parameters:")
                            for param_name, details in tool.inputSchema["properties"].items():
                                param_type = details.get("type", "any")
                                param_desc = details.get("description", "No description.")
                                print(f"      - {param_name} ({param_type}): {param_desc}")
                        else:
                            print("    Parameters: None")
                else:
                    print("  No tools found on the server.")
                print("------------------------\n")
            
            if args.single:
                logger.info(f"Calling 'check_domain' for: {args.single}")
                response = await client.call_tool("check_domain", {"domain": args.single})
                print(f"\n--- Single Domain Check: {args.single} ---")
                if response and response.data:
                    result_text = response.data
                    status_line = "Status not found"
                    # Find and print the status line separately for emphasis
                    for line in result_text.splitlines():
                        if line.startswith("Status:"):
                            status_line = line
                            break
                    print(f"\n{status_line}\n")
                    print("Full Details:")
                    print(result_text)
                else:
                    print("No valid response data received.")
                print("---------------------------------------\n")

            if args.multiple:
                logger.info(f"Calling 'check_multiple_domains' for: {args.multiple}")
                response = await client.call_tool("check_multiple_domains", {"domains": args.multiple})
                print(f"\n--- Multiple Domain Check ---")
                if response and response.data:
                    print(response.data) # The data is already formatted as a table
                else:
                    print("No valid response data received.")
                print("-----------------------------\n")

            if args.resource:
                resource_uri = f"domain://check/{args.resource}"
                logger.info(f"Calling 'get_resource' for: {resource_uri}")
                response = await client.get_resource(resource_uri)
                print(f"\n--- Resource Check: {resource_uri} ---")
                if response and response[0] and response[0].text:
                    try:
                        # The resource returns a JSON string, so we parse and pretty-print it
                        import json
                        json_data = json.loads(response[0].text)
                        print(json.dumps(json_data, indent=2))
                    except json.JSONDecodeError:
                        print("Response was not valid JSON. Raw response:")
                        print(response[0].text)
                else:
                    print("No valid resource data received.")
                print("--------------------------------------------------\n")

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        logger.error("Please ensure the domain-checker.py server is running and accessible at the specified URL.")

if __name__ == "__main__":
    asyncio.run(main())