"""
    Copyright 2018 EPAM Systems, Inc.

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.
"""
import time

from botocore.exceptions import ClientError

from syndicate.commons.log_helper import get_logger
from syndicate.core import CONFIG, CONN
from syndicate.core.conf.config_holder import ALL_REGIONS
from syndicate.core.helper import create_pool, unpack_kwargs
from syndicate.core.resources.helper import (build_description_obj,
                                             create_args_for_multi_region,
                                             validate_params)

_LOG = get_logger('syndicate.core.resources.cloud_watch_resource')


def describe_rule(name, meta, region, response=None):
    if not response:
        response = CONN.cw_events(region).get_rule(name)
    arn = response['Arn']
    del response['Arn']
    return {arn: build_description_obj(response, name, meta)}


def describe_rule_from_meta(name, meta):
    new_region_args = create_args_for_multi_region(
        [
            {'name': name,
             'meta': meta}
        ],
        ALL_REGIONS)
    responses = []
    for arg in new_region_args:
        rule = CONN.cw_events(arg['region']).get_rule(name)
        if rule:
            responses.append(rule)

    description = []
    for rule in responses:
        arn = rule['Arn']
        del rule['Arn']
        description.append({arn: build_description_obj(rule, name, meta)})
    return description


def create_cloud_watch_rule(args):
    """ Create CloudWatch rule from meta in region/regions.

    :type args: list
    """
    new_region_args = create_args_for_multi_region(args, ALL_REGIONS)
    return create_pool(_create_cloud_watch_rule_from_meta, new_region_args)


@unpack_kwargs
def _create_cloud_watch_rule_from_meta(name, meta, region):
    # validation depends on rule type
    required_parameters = ['rule_type']
    rule_type = meta.get('rule_type')
    if rule_type:
        if rule_type == 'schedule':
            required_parameters.append('expression')
    validate_params(name, meta, required_parameters)

    event_buses = meta.get('event_bus_accounts')
    response = CONN.cw_events(region).get_rule(name)
    if response:
        _LOG.warn('%s rule exists in %s.', name, region)
        return describe_rule(name=name, meta=meta, region=region,
                             response=response)
    try:
        func = RULE_TYPES[rule_type]
        func(name, meta, CONN.cw_events(region))
        if event_buses:
            time.sleep(5)
            _attach_tenant_rule_targets(name, region, event_buses)
        _LOG.info('Created cloud watch rule %s in %s.', name, region)
        response = CONN.cw_events(region).get_rule(name)
        time.sleep(5)
        return describe_rule(name=name, meta=meta, region=region,
                             response=response)
    except KeyError:
        raise AssertionError(
            'Invalid rule type: {0} for resource {1}. '
            'Please, change rule type with existing: '
            'schedule|ec2|api_call.'.format(rule_type, name))


def _attach_tenant_rule_targets(rule_name, region, event_buses):
    for event_bus in event_buses:
        target_arn = 'arn:aws:events:{0}:{1}:event-bus/default'.format(region,
                                                                       event_bus)
        existing_targets = CONN.cw_events(region).list_targets_by_rule(
            rule_name=rule_name)
        for target in existing_targets:
            if target['Arn'] == target_arn:
                _LOG.debug('Target to event bus %s is already attached',
                           target_arn)
                return
        CONN.cw_events(region).add_rule_target(rule_name=rule_name,
                                               target_arn=target_arn)


def _create_ec2_rule(rule_name, rule_meta, cw_conn):
    cw_conn.create_ec2_rule(name=rule_name,
                            instances=rule_meta.get('instance_ids'),
                            instance_states=rule_meta.get('instance_states'))


def _create_schedule_rule(rule_name, rule_meta, cw_conn):
    cw_conn.create_schedule_rule(name=rule_name,
                                 expression=rule_meta['expression'])


def _create_api_call_rule(rule_name, rule_meta, cw_conn):
    cw_conn.create_api_call_rule(name=rule_name,
                                 aws_service=rule_meta.get('aws_service'),
                                 operations=rule_meta.get('operations'),
                                 custom_pattern=rule_meta.get('custom_pattern'))


RULE_TYPES = {
    'schedule': _create_schedule_rule,
    'ec2': _create_ec2_rule,
    'api_call': _create_api_call_rule
}


def _handle_deactivation_for_cw_resources(cw_conn, region, rule_name):
    targets = cw_conn.list_targets_by_rule(rule_name)
    home_eb_arn = 'arn:aws:events:{0}:{1}:event-bus/default'.format(region,
                                                                    CONFIG.account_id)
    _LOG.debug('Home account event bus arn: %s', home_eb_arn)
    for target in targets:
        resource_arn = target['Arn']
        if resource_arn == home_eb_arn:
            cw_conn.remove_targets(rule_name, [target['Id']])
            _LOG.debug('Target %s removed', resource_arn)
    targets = cw_conn.list_targets_by_rule(rule_name)
    if targets:
        _LOG.debug('Will not remove rule, targets attached')
    else:
        _LOG.debug('Going to remove rule %s', rule_name)
        cw_conn.remove_rule(rule_name)
        _LOG.debug('Rule %s removed', rule_name)


def remove_cloud_watch_rules(args):
    create_pool(_remove_cloud_watch_rule, args)


@unpack_kwargs
def _remove_cloud_watch_rule(arn, config):
    region = arn.split(':')[3]
    resource_name = config['resource_name']
    try:
        CONN.cw_events(region).remove_rule(resource_name)
        _LOG.info('Rule %s was removed', resource_name)
    except ClientError as e:
        exception_type = e.response['Error']['Code']
        if exception_type == 'ResourceNotFoundException':
            _LOG.warn('Rule %s is not found', resource_name)
        else:
            raise e
