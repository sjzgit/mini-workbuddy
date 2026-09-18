-- 012-agent-evaluation：评测系统 5 表（与 Alembic 迁移 de50fb3128d4 对应）

CREATE TABLE evaluation_datasets (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	description VARCHAR(500) DEFAULT ('') NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_evaluation_datasets_updated_at ON evaluation_datasets (updated_at);

CREATE TABLE evaluation_cases (
	id INTEGER NOT NULL, 
	dataset_id INTEGER NOT NULL, 
	user_question TEXT NOT NULL, 
	expected_answer TEXT, 
	scoring_criteria TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(dataset_id) REFERENCES evaluation_datasets (id) ON DELETE CASCADE
);
CREATE INDEX ix_evaluation_cases_dataset ON evaluation_cases (dataset_id);

CREATE TABLE evaluation_tasks (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	agent_id INTEGER NOT NULL, 
	dataset_id INTEGER NOT NULL, 
	evaluator_type VARCHAR(30) NOT NULL, 
	evaluator_config JSON NOT NULL, 
	pass_threshold INTEGER NOT NULL, 
	agent_snapshot JSON NOT NULL, 
	dataset_snapshot JSON NOT NULL, 
	evaluator_snapshot JSON NOT NULL, 
	status VARCHAR(20) DEFAULT 'pending' NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_evaluation_tasks_dataset ON evaluation_tasks (dataset_id);

CREATE TABLE evaluation_runs (
	id INTEGER NOT NULL, 
	task_id INTEGER NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	status VARCHAR(20) DEFAULT 'pending' NOT NULL, 
	started_at DATETIME, 
	finished_at DATETIME, 
	interrupted_at DATETIME, 
	interrupted_reason VARCHAR(500), 
	total_cases INTEGER DEFAULT 0 NOT NULL, 
	completed_cases INTEGER DEFAULT 0 NOT NULL, 
	passed_cases INTEGER DEFAULT 0 NOT NULL, 
	failed_cases INTEGER DEFAULT 0 NOT NULL, 
	execution_failed_cases INTEGER DEFAULT 0 NOT NULL, 
	judge_failed_cases INTEGER DEFAULT 0 NOT NULL, 
	cancelled_cases INTEGER DEFAULT 0 NOT NULL, 
	average_score INTEGER, 
	pass_rate INTEGER, 
	total_duration_ms INTEGER, 
	total_tokens INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES evaluation_tasks (id) ON DELETE CASCADE
);
CREATE INDEX ix_evaluation_runs_status ON evaluation_runs (status);
CREATE INDEX ix_evaluation_runs_task ON evaluation_runs (task_id);
CREATE UNIQUE INDEX uq_evaluation_runs_run_id ON evaluation_runs (run_id);

CREATE TABLE evaluation_case_runs (
	id INTEGER NOT NULL, 
	evaluation_run_id INTEGER NOT NULL, 
	dataset_case_id INTEGER NOT NULL, 
	status VARCHAR(20) DEFAULT 'pending' NOT NULL, 
	agent_run_id VARCHAR(64), 
	score INTEGER, 
	reason TEXT, 
	evaluator_type VARCHAR(30), 
	evaluator_metadata JSON, 
	duration_ms INTEGER, 
	input_tokens INTEGER, 
	output_tokens INTEGER, 
	total_tokens INTEGER, 
	tool_call_count INTEGER, 
	model_call_count INTEGER, 
	iteration_count INTEGER, 
	error_type VARCHAR(30), 
	error_message VARCHAR(2000), 
	attempt INTEGER DEFAULT 1 NOT NULL, 
	started_at DATETIME, 
	finished_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(evaluation_run_id) REFERENCES evaluation_runs (id) ON DELETE CASCADE
);
CREATE INDEX ix_evaluation_case_runs_agent_run ON evaluation_case_runs (agent_run_id);
CREATE INDEX ix_evaluation_case_runs_case ON evaluation_case_runs (dataset_case_id);
CREATE INDEX ix_evaluation_case_runs_run ON evaluation_case_runs (evaluation_run_id);
