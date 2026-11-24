using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using Vrar.AI;
using Vrar.Turbine;

namespace Vrar.Tests
{
    /// <summary>
    /// Guards the copilot contract the Python service produces: the reply parses
    /// with JsonUtility, and a component id resolves to the same avatar the HUD
    /// and the focus flight use. No network is involved.
    /// </summary>
    public class CopilotTests
    {
        private TurbineRig _rig;

        [TearDown]
        public void TearDown()
        {
            if (_rig != null)
            {
                Object.Destroy(_rig.gameObject);
            }
        }

        [Test]
        public void ReplyParsesAnswerSourceAndActions()
        {
            const string json =
                "{\"answer\":\"Gearbox is critical at 4%.\",\"source\":\"llm\",\"detail\":\"\","
                + "\"actions\":[{\"type\":\"focus_component\",\"component_id\":\"gearbox\"},"
                + "{\"type\":\"set_time\",\"seconds\":150.0}]}";

            CopilotReply reply = JsonUtility.FromJson<CopilotReply>(json);

            Assert.That(reply, Is.Not.Null);
            Assert.That(reply.answer, Does.Contain("Gearbox"));
            Assert.That(reply.source, Is.EqualTo("llm"));
            Assert.That(reply.actions, Has.Length.EqualTo(2));
            Assert.That(reply.actions[0].type, Is.EqualTo(CopilotAction.FocusComponent));
            Assert.That(reply.actions[0].component_id, Is.EqualTo("gearbox"));
            Assert.That(reply.actions[1].type, Is.EqualTo(CopilotAction.SetTime));
            Assert.That(reply.actions[1].seconds, Is.EqualTo(150f).Within(1e-3f));
        }

        [UnityTest]
        public IEnumerator ComponentIdResolvesToItsAvatarIndex()
        {
            _rig = TurbineFactory.Build();
            yield return null;

            int index = CopilotPanel.IndexOfComponent(_rig, "gearbox");

            Assert.That(index, Is.GreaterThanOrEqualTo(0));
            Assert.That(_rig.Avatars[index].ComponentId, Is.EqualTo("gearbox"));
        }

        [Test]
        public void UnknownComponentAndMissingRigAreRejected()
        {
            Assert.That(CopilotPanel.IndexOfComponent(null, "gearbox"), Is.EqualTo(-1));
            Assert.That(CopilotPanel.IndexOfComponent(_rig, "reactor_core"), Is.EqualTo(-1));
            Assert.That(CopilotPanel.IndexOfComponent(_rig, string.Empty), Is.EqualTo(-1));
        }

        [Test]
        public void ClientNormalisesATrailingSlash()
        {
            var client = new CopilotClient("http://127.0.0.1:8000/");

            Assert.That(client.Endpoint, Is.EqualTo("http://127.0.0.1:8000"));
        }
    }
}
