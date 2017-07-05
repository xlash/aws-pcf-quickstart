import json
import os
import subprocess
import time
import requests

from subprocess import Popen, PIPE

import settings
# todo: spin up a class, don't use package level vars
from settings import Settings

max_retries = 5


def format_om_json_str(om_json: str):
    return json.dumps(json.loads(om_json))


def config_opsman_auth(my_settings: settings.Settings):
    # todo: get if we should ignore ssl validation (-k) out of settings
    cmd = "om -k --target {0} configure-authentication --username '{1}' --password '{2}' --decryption-passphrase '{3}'".format(
        my_settings.opsman_url, my_settings.opsman_user, my_settings.pcf_opsmanageradminpassword,
        my_settings.pcf_opsmanageradminpassword
    )
    return exponential_backoff(cmd, my_settings.debug)


def exponential_backoff(cmd, debug, attempt=0):
    out, err, returncode = run_command(cmd, debug)
    if out != "":
        print("out: {}".format(out))
    if err != "":
        print("error: {}".format(err))

    if attempt < max_retries and returncode != 0:
        print("Retrying, {}".format(attempt))
        time.sleep(attempt ** 3)
        return exponential_backoff(cmd, debug, attempt + 1)
    else:
        return out, err, returncode


def is_opsman_configured(my_settings: settings.Settings):
    # todo: get if we should ignore ssl validation out of settings
    url = my_settings.opsman_url + "/api/v0/installations"
    response = requests.get(url = url, verify=False)
    # if auth isn't configured yet, authenticated api endpoints give 400 rather than 401
    if response.status_code == 400:
        return False
    return True


def run_command(cmd: str, debug_mode):
    if debug_mode:
        print("Debug mode. Would have run command")
        print("    {}".format(cmd))
        return "", "", 0
    else:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        out_bytes, err_bytes = p.communicate()
        out = out_bytes.decode("utf-8").strip()
        err = err_bytes.decode("utf-8").strip()
        return out, err, p.returncode


def apply_changes(my_settings: settings.Settings):
    cmd = "{get_om_with_auth} apply-changes".format(
        get_om_with_auth=get_om_with_auth(my_settings)
    )
    return exponential_backoff(cmd, my_settings.debug)


def curl_get(my_settings: settings.Settings, path: str):
    cmd = "{get_om_with_auth} curl --path {path}".format(
        get_om_with_auth=get_om_with_auth(my_settings), path=path
    )
    return run_command(cmd, my_settings.debug)


def curl_payload(my_settings: settings.Settings, path: str, data: str, method: str):
    cmd = "{get_om_with_auth} curl --path {path} --request {method} --data '{data}'".format(
        get_om_with_auth=get_om_with_auth(my_settings), path=path,
        method=method, data=data
    )
    return run_command(cmd, my_settings.debug)


def stage_product(product_name: str, my_settings: settings.Settings):
    cmd = "{om_with_auth} curl --path /api/v0/available_products".format(
        om_with_auth=get_om_with_auth(my_settings)
    )
    p = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=True)
    out, err = p.communicate()
    if p.returncode != 0:
        print("Failed to query api")
        return p.returncode

    products = json.loads(out.decode())
    cf_version = [x['product_version'] for x in products if x['name'] == product_name][0]

    # ok to call multiple times, no-op when already staged
    cmd = "{om_with_auth} stage-product -p {product_name} -v {version}".format(
        om_with_auth=get_om_with_auth(my_settings),
        product_name=product_name,
        version=cf_version
    )
    return exponential_backoff(cmd, my_settings.debug)


def upload_stemcell(my_settings: settings.Settings, path: str):
    for stemcell in os.listdir(path):
        if stemcell.endswith(".tgz"):
            print("uploading stemcell {0}".format(stemcell))
            cmd = "{om_with_auth} upload-stemcell -s '{path}'".format(
                om_with_auth=get_om_with_auth(my_settings), path=os.path.join(path, stemcell)
            )
            exit_code = exponential_backoff(cmd, my_settings.debug)
            if exit_code != 0:
                return exit_code

    return 0



def upload_assets(my_settings: settings.Settings, path: str):
    for tile in os.listdir(path):
        if tile.endswith(".pivotal"):
            print("uploading product {0}".format(tile))

            cmd = "{om_with_auth} -r 3600 upload-product -p '{path}'".format(
                om_with_auth=get_om_with_auth(my_settings), path=os.path.join(path, tile))

            exit_code = exponential_backoff(cmd, my_settings.debug)
            if exit_code != 0:
                return exit_code

    return 0


def get_om_with_auth(settings: Settings):
    return "om -k --target {url} --username '{username}' --password '{password}'".format(
        url=settings.opsman_url,
        username=settings.opsman_user,
        password=settings.pcf_opsmanageradminpassword
    )
