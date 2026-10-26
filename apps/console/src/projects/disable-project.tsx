import { useState } from "react";
import type { ProjectRead } from "@harness/shared-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, type ProjectsApi } from "@/api/projects";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

export function DisableProject({
  project,
  api,
}: {
  project: ProjectRead;
  api: ProjectsApi;
}) {
  const [open, setOpen] = useState(false);
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => api.disable(project.id),
    onSuccess: async (updated) => {
      client.setQueryData(["project", project.id], updated);
      client.setQueryData<ProjectRead[]>(["projects"], (items) =>
        items?.map((item) => (item.id === updated.id ? updated : item)),
      );
      setOpen(false);
      await client.invalidateQueries({ queryKey: ["projects"] });
    },
  });
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!mutation.isPending) {
          setOpen(next);
          mutation.reset();
        }
      }}
    >
      <AlertDialogTrigger asChild>
        <Button variant="outline" disabled={project.status === "disabled"}>
          Отключить
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogTitle className="text-xl font-semibold">
          Отключить проект?
        </AlertDialogTitle>
        <AlertDialogDescription className="my-4 text-muted-foreground">
          Новые задачи и выдача настроек прекратятся. Задачи в работе продолжат
          выполняться.
        </AlertDialogDescription>
        {mutation.isError && (
          <p role="alert" className="error-box mb-4">
            {mutation.error instanceof ApiError
              ? mutation.error.message
              : "Не удалось отключить проект."}
          </p>
        )}
        <div className="flex justify-end gap-3">
          <AlertDialogCancel asChild>
            <Button variant="outline" disabled={mutation.isPending}>
              Отмена
            </Button>
          </AlertDialogCancel>
          <Button
            variant="destructive"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Отключение…" : "Подтвердить отключение"}
          </Button>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
