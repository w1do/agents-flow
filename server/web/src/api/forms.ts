import { useState, type FormEvent } from 'react';
import { useAction } from './hooks';
import { projectsApi } from './projects';
import { skillsApi, type AgentCardData, type SkillInput } from './skills';
import type { Category, Skill } from './types';

export function useSkillForm(skill: Skill | undefined, categories: Category[], onSaved: () => Promise<void>) {
  const [name, setName] = useState(skill?.name || '');
  const [description, setDescription] = useState(skill?.description || '');
  const [content, setContent] = useState(skill?.content || '');
  const [categoryId, setCategoryId] = useState(skill?.category_id || categories[0]?.id || '');
  const [warnings, setWarnings] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const action = useAction();
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await action.run(async () => {
      const input: SkillInput = { name: name.trim(), description, content, category_id: categoryId };
      const result = await skillsApi.save(input, skill?.id);
      setWarnings(result.warnings); setSaved(true);
      if (!skill) { setName(''); setDescription(''); setContent(''); }
      await onSaved();
    });
  };
  return { name, setName, description, setDescription, content, setContent, categoryId, setCategoryId,
    warnings, saved, setSaved, action, submit };
}

export function useProjectForm(onSaved: () => Promise<void>) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const action = useAction();
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await action.run(async () => {
      await projectsApi.create(name.trim(), description);
      setName(''); setDescription(''); await onSaved();
    });
  };
  return { name, setName, description, setDescription, action, submit };
}

export function useCategoryForm(onSaved: () => Promise<void>) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const action = useAction();
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await action.run(async () => {
      await skillsApi.category(name.trim(), description);
      setName(''); setDescription(''); await onSaved();
    });
  };
  return { name, setName, description, setDescription, action, submit };
}

export function useAgentSkills(agent: AgentCardData, skills: Skill[], onSaved: () => Promise<void>) {
  const [selected, setSelected] = useState(agent.skills.map(skill => skill.id));
  const [disabled, setDisabled] = useState(agent.skills.filter(skill => skill.enabled === false).map(skill => skill.id));
  const [saved, setSaved] = useState(false);
  const action = useAction();
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await action.run(async () => {
      await skillsApi.assign(agent.id, selected, disabled.filter(id => selected.includes(id)));
      setSaved(true); await onSaved();
    });
  };
  return { selected, setSelected, disabled, setDisabled, saved, setSaved, action, submit,
    available: skills.filter(skill => skill.is_active || selected.includes(skill.id)) };
}
