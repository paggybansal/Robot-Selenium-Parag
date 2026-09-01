    # ==================================================
    # NEW — TRIGGER (START) GLUE JOB WITH PARAMETERS
    # ==================================================

    @keyword("Trigger Glue Job")
    def trigger_glue_job(self, job_name, parameters=None, worker_type=None,
                         number_of_workers=None, max_capacity=None,
                         timeout_minutes=None, security_configuration=None,
                         **extra_parameters):
        """
        Trigger (start) an AWS Glue job with runtime parameters.
        Returns: RunId (string)

        Args:
            job_name              : Glue job name (mandatory)
            parameters            : Job arguments — accepts
                                      * Robot dictionary (Create Dictionary)
                                      * JSON string      '{"--env":"qa"}'
                                      * CSV string       '--env=qa,--load_type=full'
            worker_type           : Optional override — G.1X | G.2X | G.025X | Standard
            number_of_workers     : Optional override (int)
            max_capacity          : Optional override (float, python-shell jobs)
            timeout_minutes       : Optional Glue-side job timeout (minutes)
            security_configuration: Optional security configuration name
            **extra_parameters    : Inline key=value pairs ('--' prefix optional)

        Examples:
            | ${params}= | Create Dictionary | --env=qa | --load_type=full   |
            | ${run_id}= | Trigger Glue Job  | my-split-job | ${params}      |
            | ${run_id}= | Trigger Glue Job  | my-split-job | env=qa | load_type=full |
        """
        job_arguments = self._build_job_arguments(parameters, extra_parameters)

        request = {'JobName': job_name}
        if job_arguments:
            request['Arguments'] = job_arguments
        if worker_type:
            request['WorkerType'] = worker_type
        if number_of_workers:
            request['NumberOfWorkers'] = int(number_of_workers)
        if max_capacity:
            request['MaxCapacity'] = float(max_capacity)
        if timeout_minutes:
            request['Timeout'] = int(timeout_minutes)
        if security_configuration:
            request['SecurityConfiguration'] = security_configuration

        logger.info(
            f"Triggering Glue job '{job_name}' with arguments: "
            f"{json.dumps(job_arguments, indent=2)}"
        )

        try:
            response = self._client.start_job_run(**request)
            run_id = response['JobRunId']
            logger.info(f"Glue job '{job_name}' triggered → RunId: {run_id}")
            return run_id
        except self._client.exceptions.EntityNotFoundException:
            logger.error(f"Glue job not found: {job_name}")
            raise
        except self._client.exceptions.ConcurrentRunsExceededException:
            logger.error(f"Concurrent run limit exceeded for job: {job_name}")
            raise
        except Exception as e:
            logger.error(f"Error triggering Glue job '{job_name}': {e}")
            raise

    # ==================================================
    # NEW — TRIGGER + WAIT (reuses existing keywords)
    # ==================================================

    @keyword("Trigger Glue Job And Wait For Completion")
    def trigger_glue_job_and_wait_for_completion(self, job_name, parameters=None,
                                                 timeout_seconds=600, poll_interval=30,
                                                 expected_state='SUCCEEDED',
                                                 **extra_parameters):
        """
        Trigger a Glue job with parameters, then wait until it reaches a terminal state.
        Reuses 'Wait For Glue Job Completion' and 'Glue Job Run Should Have Succeeded'.

        Returns: dict from _format_run()  →  RunId, JobRunState, StartedOn,
                 CompletedOn, ExecutionTime, ErrorMessage, Arguments

        Example:
            | ${run}= | Trigger Glue Job And Wait For Completion | my-split-job | ${params} |
            | ...     | timeout_seconds=1200 | poll_interval=30 |
        """
        run_id = self.trigger_glue_job(job_name, parameters, **extra_parameters)

        status = self.wait_for_glue_job_completion(
            job_name, run_id,
            timeout_seconds=timeout_seconds,
            poll_interval=poll_interval
        )

        if expected_state:
            if expected_state == 'SUCCEEDED':
                # existing keyword already builds a rich failure message
                self.glue_job_run_should_have_succeeded(job_name, run_id)
            elif status != expected_state:
                raise AssertionError(
                    f"Glue job '{job_name}' run '{run_id}' ended with '{status}', "
                    f"expected '{expected_state}'. "
                    f"Error: {self.get_glue_job_error_message(job_name, run_id)}"
                )

        return self.get_glue_job_run_details(job_name, run_id)

    # ==================================================
    # NEW — RUN DETAILS FOR A SPECIFIC RunId
    # ==================================================

    @keyword("Get Glue Job Run Details")
    def get_glue_job_run_details(self, job_name, run_id):
        """
        Get full details of a SPECIFIC job run (same dict shape as
        'Get Latest Glue Job Run' / 'Get Glue Job Run After Time').

        Example:
            | ${run}= | Get Glue Job Run Details | my-split-job | ${RUN_ID} |
            | Log     | ${run}[Arguments]        |
        """
        try:
            response = self._client.get_job_run(JobName=job_name, RunId=run_id)
            result = self._format_run(response['JobRun'])
            logger.info(f"Run details for '{run_id}': {result}")
            return result
        except self._client.exceptions.EntityNotFoundException:
            logger.error(f"Job run not found: {job_name}/{run_id}")
            raise
        except Exception as e:
            logger.error(f"Error getting job run details: {e}")
            raise

    # ==================================================
    # NEW — ASSERTION: PARAMETERS ACTUALLY REACHED GLUE
    # ==================================================

    @keyword("Glue Job Run Should Have Arguments")
    def glue_job_run_should_have_arguments(self, job_name, run_id,
                                           expected_arguments=None, **extra_expected):
        """
        Assert the run was started with the expected arguments
        (guards against 'job passed but ran with stale parameters').

        Example:
            | Glue Job Run Should Have Arguments | my-split-job | ${RUN_ID} | ${params} |
            | Glue Job Run Should Have Arguments | my-split-job | ${RUN_ID} | env=qa    |
        """
        expected = self._build_job_arguments(expected_arguments, extra_expected)
        actual = self.get_glue_job_run_details(job_name, run_id)['Arguments']

        mismatches = []
        for key, value in expected.items():
            if key not in actual:
                mismatches.append(f"{key}: MISSING (expected '{value}')")
            elif str(actual[key]) != str(value):
                mismatches.append(f"{key}: expected '{value}', got '{actual[key]}'")

        if mismatches:
            raise AssertionError(
                f"Glue job '{job_name}' run '{run_id}' argument mismatch:\n  "
                + "\n  ".join(mismatches)
                + f"\nActual arguments: {json.dumps(actual, indent=2)}"
            )
        logger.info(f"All {len(expected)} expected argument(s) verified for run '{run_id}'")

    # ==================================================
    # NEW — PRIVATE HELPERS (parameter handling)
    # ==================================================

    def _build_job_arguments(self, parameters=None, extra_parameters=None):
        """Merge dict / JSON / CSV parameters + inline kwargs into Glue 'Arguments'."""
        merged = {}

        if parameters:
            if isinstance(parameters, dict):
                merged.update(parameters)
            elif isinstance(parameters, str):
                merged.update(self._parse_parameters_string(parameters))
            elif isinstance(parameters, (list, tuple)):
                merged.update(
                    self._parse_parameters_string(','.join(str(p) for p in parameters))
                )
            else:
                raise TypeError(
                    f"'parameters' must be a dictionary or string, "
                    f"got {type(parameters).__name__}"
                )

        if extra_parameters:
            merged.update(extra_parameters)

        arguments = {}
        for key, value in merged.items():
            if value is None:
                continue
            arguments[self._normalize_argument_key(key)] = str(value)
        return arguments

    def _parse_parameters_string(self, parameters_str):
        """Accept JSON ('{"--env":"qa"}') or CSV ('--env=qa,--load_type=full')."""
        parameters_str = parameters_str.strip()
        if not parameters_str:
            return {}

        if parameters_str.startswith('{'):
            try:
                return json.loads(parameters_str)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON parameters: {parameters_str} ({e})")

        parsed = {}
        for pair in parameters_str.replace(';', ',').split(','):
            pair = pair.strip()
            if not pair:
                continue
            if '=' not in pair:
                raise ValueError(f"Invalid parameter '{pair}'. Expected format: --key=value")
            key, value = pair.split('=', 1)
            parsed[key.strip()] = value.strip()
        return parsed

    def _normalize_argument_key(self, key):
        """Glue requires '--' prefixed argument names; block reserved ones."""
        key = str(key).strip()
        if not key.startswith('--'):
            key = f"--{key.lstrip('-')}"
        if key in self.RESERVED_ARGUMENTS:
            raise ValueError(
                f"'{key}' is a reserved AWS Glue argument and cannot be passed as a parameter"
            )
        return key
