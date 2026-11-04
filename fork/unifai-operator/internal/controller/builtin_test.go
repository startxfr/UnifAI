package controller

import (
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
)

var _ = Describe("Built-in resources", func() {
	const timeout, interval = 20 * time.Second, 200 * time.Millisecond

	gateway := func(ns string, builtin bool) *unifaiv1.UnifaiLLM {
		return &unifaiv1.UnifaiLLM{ObjectMeta: metav1.ObjectMeta{Name: "gw", Namespace: ns}, Spec: unifaiv1.UnifaiLLMSpec{
			CommonSpec: unifaiv1.CommonSpec{UnifaiName: "gw-" + ns}, Builtin: builtin, Type: "openai_compatible",
			ConfigSpec: unifaiv1.ConfigSpec{Config: raw(map[string]any{"model_name": "auto", "base_url": "http://gw:8080/v1"})}}}
	}
	toggles := func() int {
		mas.mu.Lock()
		defer mas.mu.Unlock()
		return mas.toggles
	}

	It("creates a public built-in and promotes it only when the spec changes", func() {
		ns := newNamespace("builtin")
		llm := gateway(ns, true)
		Expect(k8sClient.Create(ctx, llm)).To(Succeed())
		Eventually(phaseOf(llm), timeout, interval).Should(Equal("Ready"))
		Expect(mas.resourceByName("llms", "gw-"+ns)).To(HaveKeyWithValue("builtin", true))

		By("not promoting again on a resync")
		before := toggles()
		Expect(k8sClient.Get(ctx, client.ObjectKeyFromObject(llm), llm)).To(Succeed())
		llm.Annotations = map[string]string{"touch": "1"}
		Expect(k8sClient.Update(ctx, llm)).To(Succeed())
		Consistently(toggles, 2*time.Second, interval).Should(Equal(before))
	})

	It("promotes an existing custom resource in place", func() {
		ns := newNamespace("promote")
		llm := gateway(ns, false)
		Expect(k8sClient.Create(ctx, llm)).To(Succeed())
		Eventually(phaseOf(llm), timeout, interval).Should(Equal("Ready"))
		rid := llm.Status.RID
		Expect(mas.resourceByName("llms", "gw-"+ns)).NotTo(HaveKey("builtin"))

		llm.Spec.Builtin = true
		Expect(k8sClient.Update(ctx, llm)).To(Succeed())
		Eventually(func() bool {
			b, _ := mas.resourceByName("llms", "gw-"+ns)["builtin"].(bool)
			return b
		}, timeout, interval).Should(BeTrue())
		Expect(k8sClient.Get(ctx, client.ObjectKeyFromObject(llm), llm)).To(Succeed())
		Expect(llm.Status.RID).To(Equal(rid))

		By("refusing to turn builtin off")
		llm.Spec.Builtin = false
		err := k8sClient.Update(ctx, llm)
		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("builtin cannot be turned off"))
	})

	It("rejects builtin with a team workspace", func() {
		ns := newNamespace("builtin-team")
		llm := gateway(ns, true)
		llm.Spec.TeamRef = "some-team"
		err := k8sClient.Create(ctx, llm)
		Expect(err).To(HaveOccurred())
		Expect(err.Error()).To(ContainSubstring("builtin is exclusive with teamId and teamRef"))
	})

	It("reports a permanent error when the owner is not an UnifAI admin", func() {
		ns := newNamespace("builtin-owner")
		llm := gateway(ns, true)
		llm.Spec.Owner = "consultant-01"
		Expect(k8sClient.Create(ctx, llm)).To(Succeed())
		Eventually(phaseOf(llm), timeout, interval).Should(Equal(PhaseError))
		Expect(llm.Status.Message).To(ContainSubstring("builtin needs an UnifAI admin owner"))
	})
})
