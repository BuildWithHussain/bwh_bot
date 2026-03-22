frappe.ui.form.on("BWH Bot Settings", {
	register_webhook(frm) {
		frm.call("register_webhook").then(() => {
			frappe.show_alert({ message: "Webhook registered", indicator: "green" });
		});
	},
});
