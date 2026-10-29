import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchMe, login, logout } from "../api/auth";

export const ME_KEY = ["me"] as const;

export function useMe() {
  return useQuery({ queryKey: ME_KEY, queryFn: fetchMe, retry: false, staleTime: 60_000 });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { login: string; password: string }) => login(v.login, v.password),
    onSuccess: (user) => qc.setQueryData(ME_KEY, user),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSuccess: () => qc.setQueryData(ME_KEY, null),
  });
}
