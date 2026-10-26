import { useState } from "react";
import type { ProjectInput, ProjectRead, ProjectUpdate } from "@harness/shared-types";
import { Link } from "react-router-dom";
import { ApiError } from "@/api/projects";
import { Button } from "@/components/ui/button";
import { initialValues, projectInput, projectUpdate } from "./form-values";
import { ProjectFields } from "./project-fields";
import { serverFieldErrors, validateProject, type FieldErrors } from "./validation";

type Props = {
  project?: ProjectRead;
  onSave: (data: ProjectInput | ProjectUpdate) => Promise<void>;
};

export function ProjectForm({ project, onSave }: Props) {
  const [values, setValues] = useState(() => initialValues(project));
  const [errors, setErrors] = useState<FieldErrors>({});
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  return (
    <form
      noValidate
      onSubmit={async (event) => {
        event.preventDefault();
        if (saving) return;
        const invalid = validateProject(values, !project);
        setErrors(invalid);
        setMessage("");
        if (Object.keys(invalid).length) {
          setMessage("Проверьте отмеченные поля.");
          return;
        }
        setSaving(true);
        try {
          await onSave(project ? projectUpdate(values, project) : projectInput(values));
        } catch (error) {
          setMessage(
            error instanceof ApiError ? error.message : "Не удалось сохранить проект.",
          );
          if (error instanceof ApiError) setErrors(serverFieldErrors(error.fields));
        } finally {
          setSaving(false);
        }
      }}
      className="space-y-7"
    >
      {message && (
        <p role="alert" className="error-box">
          {message}
        </p>
      )}
      <fieldset disabled={saving} className="min-w-0">
        <ProjectFields
          values={values}
          errors={errors}
          creating={!project}
          onChange={setValues}
        />
      </fieldset>
      <div className="flex gap-3 border-t pt-6">
        <Button type="submit" disabled={saving}>
          {saving ? "Сохранение…" : project ? "Сохранить изменения" : "Создать проект"}
        </Button>
        <Button variant="outline" asChild>
          <Link to="/projects">Отмена</Link>
        </Button>
      </div>
    </form>
  );
}
