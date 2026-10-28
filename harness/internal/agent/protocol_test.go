package agent

import (
	"testing"

	"agentsflow/harness/internal/api"
)

func TestRussianSkillCategoriesAreStageFiltered(t *testing.T) {
	files := []api.Skill{
		{Category: "Деплой", Name: "release"},
		{Category: "Публикация проекта", Name: "publish"},
		{Category: "Тестирование", Name: "tests"},
		{Category: "Разработка", Name: "code"},
	}
	planning := stageSkills(files, "planning")
	for _, file := range planning {
		if file.Category == "Деплой" || file.Category == "Публикация проекта" {
			t.Fatal("publication skill passed before publication", file.Category)
		}
	}
	publishing := stageSkills(files, "publication")
	if len(publishing) != 2 {
		t.Fatalf("publication skills = %d, want 2", len(publishing))
	}
	testingSkills := stageSkills(files, "testing")
	found := false
	for _, file := range testingSkills {
		if file.Category == "Тестирование" {
			found = true
		}
	}
	if !found {
		t.Fatal("Russian testing category was not selected")
	}
}
