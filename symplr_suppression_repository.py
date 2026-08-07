    def find_candidates_for_rule(
            self,
            rule,
            *,
            top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        """Find candidates using the entity-specific SQL configured by the rule."""
        sql = load_sql(rule.candidate_sql)
        sql = bind_literal_int(sql, "top_n", top_n, minimum=1, maximum=1000)
        sql = bind_in_clause(
            sql,
            "qualifying_value_placeholders",
            list(rule.qualifying_udf_values),
            "?",
        )

        params = (
            rule.udf_field_name,
            rule.trigger_value,
            *rule.qualifying_udf_values,
        )

        assert_param_count(
            sql,
            params,
            paramstyle="?",
            label=f"find_candidates_for_rule[{rule.key}]",
        )

        with symplr_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return fetch_all_as_dicts(cur)

    def count_candidates_for_rule(self, rule) -> int:
        """Count eligible entity records for the configured rule."""
        sql = load_sql(rule.candidate_count_sql)
        sql = bind_in_clause(
            sql,
            "qualifying_value_placeholders",
            list(rule.qualifying_udf_values),
            "?",
        )

        params = (
            rule.udf_field_name,
            rule.trigger_value,
            *rule.qualifying_udf_values,
        )

        assert_param_count(
            sql,
            params,
            paramstyle="?",
            label=f"count_candidates_for_rule[{rule.key}]",
        )

        with symplr_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()

        return int(row[0]) if row and row[0] is not None else 0

    def get_final_state(
            self,
            rule,
            candidate: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Read the final database row using the rule's configured primary key."""
        sql = load_sql(rule.final_state_sql)
        params = tuple(candidate[column] for column in rule.final_key_columns)

        assert_param_count(
            sql,
            params,
            paramstyle="?",
            label=f"get_final_state[{rule.key}]",
        )

        with symplr_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)

            result = cur.fetchone()
            if not result:
                return None

            columns = [column[0] for column in cur.description]
            return dict(zip(columns, result))
